"""Base commune des tests : import du projet + dossiers temporaires."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import audio as _audio   # noqa: E402
from app import jobs as _jobs     # noqa: E402
from app import state as _state   # noqa: E402


class AppTestCase(unittest.TestCase):
    """Reoriente outputs/ et refs/ vers un dossier temporaire par test.

    Chaque module (state, audio, jobs) porte sa propre liaison vers ces
    dossiers : les quatre sont remplaces puis restaurés.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="voxcpm_tests_")
        self._saved = (_state.OUTPUTS_DIR, _state.REFS_DIR,
                       _audio.OUTPUTS_DIR, _jobs.REFS_DIR)
        _state.OUTPUTS_DIR = _audio.OUTPUTS_DIR = os.path.join(self._tmp, "outputs")
        _state.REFS_DIR = _jobs.REFS_DIR = os.path.join(self._tmp, "refs")
        os.makedirs(_state.OUTPUTS_DIR, exist_ok=True)
        os.makedirs(_state.REFS_DIR, exist_ok=True)

    def tearDown(self):
        (_state.OUTPUTS_DIR, _state.REFS_DIR,
         _audio.OUTPUTS_DIR, _jobs.REFS_DIR) = self._saved
        shutil.rmtree(self._tmp, ignore_errors=True)
