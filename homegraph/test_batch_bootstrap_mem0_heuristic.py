from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from homegraph.batch_bootstrap_mem0_heuristic import build_output_path, process_export_file


class BatchBootstrapMem0HeuristicTests(unittest.TestCase):
    def test_process_export_file_writes_heuristic_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            export_path = temp_path / "alice_export.json"
            export_path.write_text(
                json.dumps(
                    {
                        "user_id": "twitch:streamer:viewer:alice",
                        "channel": "streamer",
                        "viewer": "alice",
                        "memories": [
                            {
                                "id": "mem_1",
                                "memory": "Je joue surtout a Satisfactory et j'adore optimiser mes usines.",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = process_export_file(export_path, temp_path, merge=False, db_path=str(temp_path / "db.sqlite3"))
            output_path = build_output_path(temp_path, export_path)

            self.assertTrue(output_path.exists())
            extraction = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["viewer_id"], "twitch:streamer:viewer:alice")
            self.assertEqual(extraction["viewer_id"], "twitch:streamer:viewer:alice")
            self.assertTrue(any(link["relation_type"] == "plays" for link in extraction["links"]))


if __name__ == "__main__":
    unittest.main()
