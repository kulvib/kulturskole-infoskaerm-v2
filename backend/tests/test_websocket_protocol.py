from __future__ import annotations

import unittest

from service1.websocket_protocol import ProtocolError, bounded_int, bounded_text, decode_json_message


class WebSocketProtocolTests(unittest.TestCase):
    def test_decodes_object_and_normalizes_type(self) -> None:
        decoded = decode_json_message(' {"type":" ping ","value":1} ', allowed_types={"ping"})
        self.assertEqual(decoded.type, "ping")
        self.assertEqual(decoded.payload["type"], "ping")

    def test_rejects_invalid_json_non_object_and_missing_type(self) -> None:
        for raw in ("{", "[]", '{"value":1}'):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                decode_json_message(raw)

    def test_rejects_unknown_type_with_existing_error_contract(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "Ukendt terminaltype: shell"):
            decode_json_message(
                '{"type":"shell"}',
                allowed_types={"open"},
                unknown_type_prefix="Ukendt terminaltype",
            )

    def test_rejects_oversized_message_with_1009(self) -> None:
        with self.assertRaises(ProtocolError) as caught:
            decode_json_message("x" * 11, max_chars=10)
        self.assertEqual(caught.exception.close_code, 1009)

    def test_bounded_text_preserves_and_limits_wire_values(self) -> None:
        self.assertEqual(bounded_text({"data": 12}, "data", maximum=5), "12")
        with self.assertRaisesRegex(ProtocolError, "Terminal-input er for langt"):
            bounded_text(
                {"data": "abcdef"},
                "data",
                maximum=5,
                too_long_message="Terminal-input er for langt",
            )

    def test_bounded_int_uses_default_and_clamps(self) -> None:
        self.assertEqual(bounded_int("bad", default=40, minimum=20, maximum=300), 40)
        self.assertEqual(bounded_int(999, default=40, minimum=20, maximum=300), 300)


if __name__ == "__main__":
    unittest.main()
