import unittest

from app_events.contract import documento_subido, lectura_solicitada
from lector_core.detect import detect_language
from lector_core.extractor import DocumentExtractor
from lector_core.tts import VoiceSynthesizer
from workers.consumer_tts import ConsumerTTS


class CoreBehaviorTests(unittest.TestCase):
    def test_event_payloads_use_string_fields(self):
        self.assertEqual(
            documento_subido("doc-1", "data/doc.pdf", "doc.pdf"),
            {"doc_id": "doc-1", "fuente": "data/doc.pdf", "nombre": "doc.pdf"},
        )
        self.assertEqual(
            lectura_solicitada("doc-1", 2, "en", "en-US-AriaNeural"),
            {
                "doc_id": "doc-1",
                "chunk_index": "2",
                "target_lang": "en",
                "voz": "en-US-AriaNeural",
            },
        )

    def test_text_is_split_into_complete_reading_units(self):
        self.assertEqual(
            DocumentExtractor._split_reading_units("Una frase\nque continúa. Otra frase; sigue aquí."),
            ["Una frase que continúa. Otra frase; sigue aquí."],
        )

    def test_language_detection_and_voice_defaults(self):
        self.assertEqual(detect_language("This is a sufficiently long English sentence."), "en")
        self.assertEqual(VoiceSynthesizer.best_voice_for("en"), "en-US-AriaNeural")
        self.assertEqual(VoiceSynthesizer.best_voice_for("unknown"), "es-MX-DaliaNeural")

    def test_audio_cues_keep_document_chunk_indexes(self):
        timings = [{"text": word} for word in ["uno", "dos", "tres"]]
        ConsumerTTS._assign_chunk_indexes(timings, ["uno dos", "tres"])
        self.assertEqual([cue["chunk_index"] for cue in timings], [0, 0, 1])
        self.assertEqual([cue["word_index"] for cue in timings], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
