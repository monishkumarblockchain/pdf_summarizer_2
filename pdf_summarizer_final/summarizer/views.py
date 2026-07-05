from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .forms import PDFUploadForm, QuestionForm
from .models import PDFDocument
from .utils import generate_pdf_summary, answer_question_about_document, PDFSummaryError


def upload_pdf(request):
    """
    Part 2: upload a PDF, then immediately run it through the
    map-reduce summarization pipeline and store the result.
    """
    if request.method == "POST":
        form = PDFUploadForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save()

            try:
                summary = generate_pdf_summary(document.file.path)
                document.summary = summary
                document.summary_error = ""
                document.save()
                messages.success(
                    request,
                    f"'{document.original_filename}' uploaded and summarized."
                )
            except PDFSummaryError as e:
                document.summary_error = str(e)
                document.save()
                messages.error(
                    request,
                    f"'{document.original_filename}' uploaded, but summarization failed: {e}"
                )
            except Exception as e:
                # Catch-all so an unexpected error never shows a raw Django 500 page
                document.summary_error = f"Unexpected error: {e}"
                document.save()
                messages.error(
                    request,
                    f"'{document.original_filename}' uploaded, but an unexpected error "
                    f"occurred during summarization."
                )

            return redirect("upload_pdf")
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = PDFUploadForm()

    recent_documents = PDFDocument.objects.all()[:10]

    return render(request, "summarizer/index.html", {
        "form": form,
        "recent_documents": recent_documents,
    })


def chat_with_pdf(request, doc_id):
    """
    Part 5: RAG chat for a single PDF.

    On first question, the PDF gets embedded and stored in a dedicated
    Chroma collection (see ensure_document_indexed in utils.py).
    Every question after that reuses the persisted collection, so
    indexing only happens once per document.

    Chat history here is intentionally simple (session-based, per
    document) rather than saved to the database — good enough to see
    RAG working end-to-end; swap in a ChatMessage model if you want
    permanent history.
    """
    document = get_object_or_404(PDFDocument, id=doc_id)

    session_key = f"chat_history_{doc_id}"
    history = request.session.get(session_key, [])

    if request.method == "POST":
        form = QuestionForm(request.POST)
        if form.is_valid():
            question = form.cleaned_data["question"]
            try:
                answer = answer_question_about_document(document, question)
                history.append({"question": question, "answer": answer, "error": False})
            except PDFSummaryError as e:
                history.append({"question": question, "answer": str(e), "error": True})
            except Exception as e:
                history.append({
                    "question": question,
                    "answer": f"Unexpected error: {e}",
                    "error": True,
                })

            request.session[session_key] = history
            return redirect("chat_with_pdf", doc_id=doc_id)
    else:
        form = QuestionForm()

    return render(request, "summarizer/chat.html", {
        "document": document,
        "form": form,
        "history": history,
    })


def clear_chat_history(request, doc_id):
    """Clears the Q&A history for a document (does not delete the Chroma index)."""
    session_key = f"chat_history_{doc_id}"
    request.session.pop(session_key, None)
    return redirect("chat_with_pdf", doc_id=doc_id)
