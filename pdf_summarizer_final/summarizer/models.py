from django.db import models


class PDFDocument(models.Model):
    """
    Represents a single uploaded PDF.
    In Part 4 we'll add a `summary` TextField here and start saving
    generated summaries against each upload.
    """
    file = models.FileField(upload_to="pdfs/")
    original_filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    summary = models.TextField(blank=True, default="")
    summary_error = models.TextField(blank=True, default="")
    is_indexed = models.BooleanField(default=False)
    index_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.original_filename or self.file.name

    def save(self, *args, **kwargs):
        if not self.original_filename and self.file:
            self.original_filename = self.file.name
        super().save(*args, **kwargs)
