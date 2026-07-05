"""
Core AI logic: extract text from a PDF, split it into chunks, and
generate a summary using a map-reduce approach with ChatGroq.

Map-reduce summarization, in plain terms:
1. MAP:    summarize each chunk of the PDF individually (chunks can be
           summarized in any order, independently of each other)
2. REDUCE: combine those individual summaries into one final summary

This avoids ever sending the entire PDF to the LLM in one request,
which would blow past context/token limits for longer documents.
"""

from django.conf import settings
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_groq import ChatGroq
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate


MAP_PROMPT = ChatPromptTemplate.from_template(
    """Summarize the following section of a document in 3-5 concise sentences.
Capture only the key facts and ideas. Do not add opinions or outside information.

Section:
{text}

Summary:"""
)

REDUCE_PROMPT = ChatPromptTemplate.from_template(
    """You are given several partial summaries covering different sections
of the same document, in order. Combine them into a single, well-organized
final summary of the whole document. Use clear paragraphs. Do not repeat
the same point twice. Do not mention that this was built from partial summaries.

Partial summaries:
{text}

Final summary:"""
)

RAG_PROMPT = ChatPromptTemplate.from_template(
    """You are a helpful assistant answering questions about a specific PDF document.

Answer ONLY using the context below. If the answer is not contained in the
context, reply exactly: "I couldn't find that information in the PDF."

Context:
{context}

Question:
{question}

Answer:"""
)


class PDFSummaryError(Exception):
    """Raised when a PDF cannot be extracted or summarized."""
    pass


def extract_pdf_documents(pdf_path):
    """Load a PDF from disk into LangChain Document objects (one per page)."""
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    if not documents or all(not doc.page_content.strip() for doc in documents):
        raise PDFSummaryError(
            "No extractable text was found in this PDF. "
            "It may be a scanned/image-only document that would need OCR."
        )

    return documents


def split_documents(documents, chunk_size=3000, chunk_overlap=200):
    """Split page-level documents into smaller overlapping chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(documents)


def get_llm():
    """Create the ChatGroq client, failing loudly if the API key is missing."""
    if not settings.GROQ_API_KEY:
        raise PDFSummaryError(
            "GROQ_API_KEY is not set. Add it to your .env file and restart the server."
        )

    return ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=settings.GROQ_API_KEY,
        temperature=0.2,
    )


def generate_pdf_summary(pdf_path):
    """
    Full pipeline: extract -> split -> map (summarize each chunk) ->
    reduce (combine into one summary). Returns the final summary text.
    """
    documents = extract_pdf_documents(pdf_path)
    chunks = split_documents(documents)

    llm = get_llm()
    map_chain = MAP_PROMPT | llm
    reduce_chain = REDUCE_PROMPT | llm

    # --- MAP step ---
    partial_summaries = []
    for chunk in chunks:
        try:
            response = map_chain.invoke({"text": chunk.page_content})
            partial_summaries.append(response.content)
        except Exception as e:
            raise PDFSummaryError(f"Failed while summarizing part of the PDF: {e}") from e

    # Small PDF that fit in a single chunk - no need to reduce further.
    if len(partial_summaries) == 1:
        return partial_summaries[0]

    # --- REDUCE step ---
    combined_text = "\n\n".join(
        f"Section {i + 1}: {summary}" for i, summary in enumerate(partial_summaries)
    )

    try:
        final_response = reduce_chain.invoke({"text": combined_text})
    except Exception as e:
        raise PDFSummaryError(f"Failed while combining section summaries: {e}") from e

    return final_response.content


# =====================================================================
# RAG (Retrieval-Augmented Generation) — ask questions about a PDF
# =====================================================================

CHROMA_BASE_DIR = settings.BASE_DIR / "chroma_db"


def get_embeddings():
    """Create the Google embeddings client used to build/query Chroma."""
    if not settings.GOOGLE_API_KEY:
        raise PDFSummaryError(
            "GOOGLE_API_KEY is not set. Add it to your .env file and restart the server."
        )

    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=settings.GOOGLE_API_KEY,
    )


def _collection_name(document_id):
    return f"pdf_{document_id}"


def _persist_dir(document_id):
    return str(CHROMA_BASE_DIR / f"doc_{document_id}")


def build_vectorstore_for_document(document):
    """
    Extract + chunk the PDF, embed every chunk, and persist it to a
    Chroma collection dedicated to this document (one collection per PDF,
    so questions on one document never leak context from another).
    """
    documents = extract_pdf_documents(document.file.path)
    # Smaller chunks than the summarizer uses — better precision for Q&A retrieval.
    chunks = split_documents(documents, chunk_size=1000, chunk_overlap=200)

    embedding = get_embeddings()

    return Chroma.from_documents(
        documents=chunks,
        embedding=embedding,
        persist_directory=_persist_dir(document.id),
        collection_name=_collection_name(document.id),
    )


def load_vectorstore_for_document(document):
    """Reopen an already-built Chroma collection for this document."""
    embedding = get_embeddings()
    return Chroma(
        persist_directory=_persist_dir(document.id),
        collection_name=_collection_name(document.id),
        embedding_function=embedding,
    )


def ensure_document_indexed(document):
    """
    Build the vector store the first time a document is chatted with.
    Subsequent questions reuse the persisted Chroma collection instead
    of re-embedding the PDF every time.
    """
    if document.is_indexed:
        return

    try:
        build_vectorstore_for_document(document)
        document.is_indexed = True
        document.index_error = ""
        document.save()
    except Exception as e:
        document.index_error = str(e)
        document.save()
        raise PDFSummaryError(f"Failed to index PDF for chat: {e}") from e


def answer_question_about_document(document, question, k=4):
    """
    Full RAG pipeline: make sure the document is indexed, retrieve the
    most relevant chunks for the question, then ask the LLM to answer
    using only that retrieved context.
    """
    ensure_document_indexed(document)

    db = load_vectorstore_for_document(document)
    retriever = db.as_retriever(search_kwargs={"k": k})
    relevant_docs = retriever.invoke(question)

    if not relevant_docs:
        return "I couldn't find that information in the PDF."

    context = "\n\n".join(doc.page_content for doc in relevant_docs)

    llm = get_llm()
    chain = RAG_PROMPT | llm

    try:
        response = chain.invoke({"context": context, "question": question})
    except Exception as e:
        raise PDFSummaryError(f"Failed to generate an answer: {e}") from e

    return response.content
