"""Unit tests for rag_sync_service — embedding model singleton."""
from unittest.mock import MagicMock, patch

import pytest


class TestEmbeddingModelSingleton:
    """Test that _get_embedding_model returns a singleton.

    SentenceTransformer is imported lazily inside _get_embedding_model, so
    we patch the source package (sentence_transformers) rather than the
    rag_sync_service module itself.
    """

    def test_singleton_returns_same_instance(self):
        """Calling _get_embedding_model twice returns the same object."""
        # Reset global state for test isolation
        import app.services.rag_sync_service as mod
        mod._embedding_model = None

        mock_model = MagicMock()
        with (
            patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st,
            patch("torch.cuda.is_available", return_value=False),
        ):
            model1 = mod._get_embedding_model()
            model2 = mod._get_embedding_model()

        # SentenceTransformer should be constructed only once
        mock_st.assert_called_once_with("BAAI/bge-m3", device="cpu", local_files_only=True)
        # Both calls return the same instance
        assert model1 is model2
        assert model1 is mock_model

    def test_import_error_propagated(self):
        """If sentence_transformers is not installed, the error propagates."""
        import app.services.rag_sync_service as mod
        mod._embedding_model = None

        with patch("sentence_transformers.SentenceTransformer", side_effect=ImportError("no module")):
            with pytest.raises(ImportError, match="no module"):
                mod._get_embedding_model()
