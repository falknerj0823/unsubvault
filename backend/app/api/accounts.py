from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core import audit
from app.core.crypto import encrypt
from app.core.database import get_db
from app.models.account import Account, ProviderType

router = APIRouter()

class IMAPAccountCreate(BaseModel):
    label: str
    host: str
    port: int = 993
    username: str
    password: str

@router.get("/")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    return [{"id": a.id, "label": a.label, "provider_type": a.provider_type.value, "email_address": a.email_address} for a in accounts]

@router.post("/imap")
def add_imap_account(body: IMAPAccountCreate, request: Request, db: Session = Depends(get_db)):
    acct = Account(label=body.label, provider_type=ProviderType.imap,
                   email_address=body.username, imap_host=body.host,
                   imap_port=body.port, imap_username=body.username,
                   imap_password_encrypted=encrypt(body.password))
    db.add(acct); db.commit(); db.refresh(acct)
    audit.record("account_added", request=request, detail={"provider": "imap", "account_id": acct.id, "host": body.host, "username": body.username})
    return {"id": acct.id}

@router.delete("/{account_id}")
def delete_account(account_id: int, request: Request, db: Session = Depends(get_db)):
    acct = db.query(Account).filter(Account.id == account_id).first()
    info = {"account_id": account_id, "provider": acct.provider_type.value, "email": acct.email_address} if acct else {"account_id": account_id, "found": False}
    db.query(Account).filter(Account.id == account_id).delete()
    db.commit()
    audit.record("account_removed", success=acct is not None, request=request, detail=info)
    return {"ok": True}

@router.get("/{account_id}/folders")
def list_folders(account_id: int, db: Session = Depends(get_db)):
    """Folders on the mail server, for the scan folder picker."""
    from app.services.scanner import ScanError, _client_for, _friendly_imap_error
    acct = db.query(Account).filter(Account.id == account_id).first()
    if not acct:
        raise HTTPException(404, "No such account")
    try:
        return {"folders": _client_for(acct, db).list_folders()}
    except ScanError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, _friendly_imap_error(e))
