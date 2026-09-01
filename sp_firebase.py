"""Firebase layer with graceful degradation.

DESIGN INTENT: the app must run fully without Firebase configured. If
credentials are absent, everything falls back to Streamlit session state --
you lose persistence between sessions, but nothing breaks and no code path
has to care which mode it's in. Add credentials later and persistence turns
on with no code changes.

Call is_live() if you need to tell the user which mode they're in.
"""
import json
import io
import streamlit as st

_FB = {"app": None, "db": None, "bucket": None, "live": False, "error": None}


def _init():
    """Initialise once per process. Safe to call repeatedly."""
    if _FB["app"] is not None or _FB["error"] is not None:
        return

    try:
        creds_raw = st.secrets.get("FIREBASE_SERVICE_ACCOUNT")
        bucket_name = st.secrets.get("FIREBASE_STORAGE_BUCKET")
    except Exception:
        creds_raw, bucket_name = None, None

    if not creds_raw:
        _FB["error"] = "not_configured"
        return

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore, storage

        # Accept either a TOML table or a pasted JSON string
        creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)

        if not firebase_admin._apps:
            cred = credentials.Certificate(creds_dict)
            opts = {"storageBucket": bucket_name} if bucket_name else None
            _FB["app"] = firebase_admin.initialize_app(cred, opts)
        else:
            _FB["app"] = firebase_admin.get_app()

        _FB["db"] = firestore.client()
        _FB["bucket"] = storage.bucket() if bucket_name else None
        _FB["live"] = True
    except Exception as e:
        _FB["error"] = str(e)


def is_live() -> bool:
    _init()
    return _FB["live"]


def status_note() -> str:
    _init()
    if _FB["live"]:
        return "Cloud sync active"
    if _FB["error"] == "not_configured":
        return "Session only — add Firebase credentials to save projects between sessions"
    return f"Session only — Firebase error: {_FB['error']}"


def has_storage() -> bool:
    """Storage requires the Blaze plan; Firestore alone works on Spark."""
    _init()
    return _FB["live"] and _FB["bucket"] is not None


# ---------------------------------------------------------------- Firestore

def doc_set(collection, doc_id, data):
    _init()
    if not _FB["live"]:
        return False
    try:
        _FB["db"].collection(collection).document(doc_id).set(data, merge=True)
        return True
    except Exception:
        return False


def doc_get(collection, doc_id):
    _init()
    if not _FB["live"]:
        return None
    try:
        snap = _FB["db"].collection(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None
    except Exception:
        return None


def doc_list(collection, where=None, order_by=None, limit=200):
    """where: optional (field, op, value) tuple."""
    _init()
    if not _FB["live"]:
        return []
    try:
        q = _FB["db"].collection(collection)
        if where:
            # Positional .where(field, op, value) is deprecated in current
            # firebase-admin and warns loudly; FieldFilter is the supported
            # form. Fall back for older installs.
            try:
                from google.cloud.firestore_v1.base_query import FieldFilter
                q = q.where(filter=FieldFilter(where[0], where[1], where[2]))
            except ImportError:
                q = q.where(where[0], where[1], where[2])
        if order_by:
            q = q.order_by(order_by)
        docs = q.limit(limit).stream()
        out = []
        for d in docs:
            item = d.to_dict() or {}
            item["_id"] = d.id
            out.append(item)
        return out
    except Exception:
        return []


def doc_delete(collection, doc_id):
    _init()
    if not _FB["live"]:
        return False
    try:
        _FB["db"].collection(collection).document(doc_id).delete()
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ Storage

def upload_bytes(path, data, content_type="application/octet-stream"):
    """Returns the storage path on success, None otherwise."""
    _init()
    if not has_storage():
        return None
    try:
        blob = _FB["bucket"].blob(path)
        blob.upload_from_string(data, content_type=content_type)
        return path
    except Exception:
        return None


def download_bytes(path):
    _init()
    if not has_storage():
        return None
    try:
        blob = _FB["bucket"].blob(path)
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception:
        return None


def delete_blob(path):
    _init()
    if not has_storage():
        return False
    try:
        _FB["bucket"].blob(path).delete()
        return True
    except Exception:
        return False
