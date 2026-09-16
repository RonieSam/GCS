"""
Phase 6 tests for safety_manager.SafetyStateMachine.

Run from backend/:
    python3 -m unittest tests.test_safety_manager -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from safety_manager import CONNECTED, CONNECTING, DISCONNECTED, HEARTBEAT_LOST, SafetyStateMachine


class TestSafetyStateMachine(unittest.TestCase):
    def test_starts_disconnected(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        self.assertEqual(sm.state, DISCONNECTED)
        self.assertFalse(sm.is_connected())

    def test_connecting_transition(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        self.assertEqual(sm.state, CONNECTING)
        self.assertFalse(sm.is_connected())

    def test_heartbeat_moves_to_connected(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        sm.heartbeat_received(at=1000.0)
        self.assertEqual(sm.state, CONNECTED)
        self.assertTrue(sm.is_connected())

    def test_disconnect_from_any_state(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        sm.heartbeat_received(at=1000.0)
        sm.disconnect()
        self.assertEqual(sm.state, DISCONNECTED)
        self.assertFalse(sm.is_connected())

    def test_check_timeout_no_effect_while_not_connected(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        result = sm.check_timeout(now=999999.0)
        self.assertEqual(result, CONNECTING)

    def test_check_timeout_flips_to_heartbeat_lost(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        sm.heartbeat_received(at=1000.0)
        result = sm.check_timeout(now=1006.0)  # 6s later, timeout is 5s
        self.assertEqual(result, HEARTBEAT_LOST)
        self.assertFalse(sm.is_connected())

    def test_check_timeout_stays_connected_within_window(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        sm.heartbeat_received(at=1000.0)
        result = sm.check_timeout(now=1003.0)  # 3s later, within the 5s window
        self.assertEqual(result, CONNECTED)

    def test_heartbeat_after_loss_recovers_to_connected(self):
        sm = SafetyStateMachine(heartbeat_timeout_s=5)
        sm.connecting()
        sm.heartbeat_received(at=1000.0)
        sm.check_timeout(now=1010.0)
        self.assertEqual(sm.state, HEARTBEAT_LOST)

        sm.heartbeat_received(at=1011.0)
        self.assertEqual(sm.state, CONNECTED)
        self.assertTrue(sm.is_connected())


if __name__ == "__main__":
    unittest.main()
