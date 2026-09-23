from django.core.mail.backends.console import EmailBackend


class ReadableConsoleEmailBackend(EmailBackend):
    """Print email content without MIME soft line breaks for local testing."""

    def write_message(self, message):
        self.stream.write(f"Subject: {message.subject}\n")
        self.stream.write(f"From: {message.from_email}\n")
        self.stream.write(f"To: {', '.join(message.to)}\n\n")
        self.stream.write(message.body)
        if not message.body.endswith("\n"):
            self.stream.write("\n")
        self.stream.write("-" * 79 + "\n")
