from google.auth.transport import requests
from google.oauth2 import id_token


def verify_google_token(credential, client_id):
    """Verify Google's signature, issuer, expiry, and this app's audience."""
    return id_token.verify_oauth2_token(credential, requests.Request(), client_id)
