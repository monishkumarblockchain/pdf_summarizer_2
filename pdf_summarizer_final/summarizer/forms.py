from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import PDFDocument


class PDFUploadForm(forms.ModelForm):
    """
    Handles PDF upload with two validation checks:
    1. File extension must be .pdf
    2. File size must not exceed settings.MAX_UPLOAD_SIZE_MB
    """

    class Meta:
        model = PDFDocument
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "application/pdf",
            }),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")

        if not uploaded_file:
            raise ValidationError("Please select a file to upload.")

        # --- Extension check ---
        if not uploaded_file.name.lower().endswith(".pdf"):
            raise ValidationError("Only PDF files are allowed.")

        # --- Content-type check (basic extra safety, not foolproof) ---
        if uploaded_file.content_type not in ("application/pdf",):
            raise ValidationError("Uploaded file does not appear to be a valid PDF.")

        # --- Size check ---
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if uploaded_file.size > max_bytes:
            raise ValidationError(
                f"File is too large. Maximum allowed size is "
                f"{settings.MAX_UPLOAD_SIZE_MB} MB."
            )

        return uploaded_file


class QuestionForm(forms.Form):
    """A single question typed into the chat box for a specific PDF."""
    question = forms.CharField(
        max_length=500,
        label="",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ask a question about this PDF...",
            "autocomplete": "off",
        }),
    )
