"""One reviewed CaptureBrief clipboard repair. Generates bytes; never publishes."""
from __future__ import annotations
import hashlib

REPOSITORY = 'P00NSMASHER/capturebrief'
BRANCH = 'gh-pages'
PATH = 'assets/capturebrief.js'
ORIGINAL_BLOB = '24c28e6a2a65ef68d1b37c16286d46ec39d1eed9'
OLD = '''      helper.select();
      const copied = document.execCommand && document.execCommand('copy');
      helper.remove();
'''
NEW = '''      const previousFocus = document.activeElement;
      let copied = false;
      try {
        helper.select();
        copied = typeof document.execCommand === 'function' && document.execCommand('copy') === true;
      } catch (_) {
        copied = false;
      } finally {
        helper.remove();
        if (previousFocus && previousFocus.isConnected && typeof previousFocus.focus === 'function') {
          previousFocus.focus({ preventScroll: true });
        }
      }
'''

def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()

def prepare(original: bytes) -> dict:
    if type(original) is not bytes or git_blob(original) != ORIGINAL_BLOB:
        raise ValueError('CLIPBOARD_ORIGINAL_SOURCE_NOT_REVIEWED')
    text = original.decode('utf-8')
    if text.count(OLD) != 1 or NEW in text:
        raise ValueError('CLIPBOARD_RECIPE_AMBIGUOUS')
    corrected = text.replace(OLD, NEW, 1).encode('utf-8')
    return dict(repository=REPOSITORY, branch=BRANCH, path=PATH,
                original_blob=ORIGINAL_BLOB, corrected_blob=git_blob(corrected),
                original_sha256=hashlib.sha256(original).hexdigest(),
                corrected_sha256=hashlib.sha256(corrected).hexdigest(),
                corrected=corrected, provider_writes=0,
                production_accepted=False)
