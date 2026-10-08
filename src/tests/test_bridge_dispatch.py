import unittest
from win_bridge import WinMessageBridge

class Native:
 WM_MOUSEMOVE=0x200
 def __init__(self):self.messages=[]
 def PostMessage(self,*args):self.messages.append(args)

class DispatchTests(unittest.TestCase):
 def make(self):
  b=object.__new__(WinMessageBridge);b.closed=False;b.scheduler=object()
  b.pending={};b._interp=123;b.gui=Native();b.con=b.gui
  b._native_eval=lambda *args:(b.gui.messages.append(args) or 0)
  return b
 def test_delivery_does_not_call_tk_from_native_handler(self):
  b=self.make();calls=[];b._dispatch(calls.append,'wake')
  self.assertEqual(calls,[]);self.assertEqual(len(b.pending),1)
  self.assertEqual([m[0] for m in b.gui.messages],[123])
  self.assertIn(b"-when tail",b.gui.messages[0][1])
  b._deliver();self.assertEqual(calls,['wake']);self.assertFalse(b.pending)
 def test_duplicate_wakes_coalesce_then_can_rearm(self):
  b=self.make();calls=[]
  for _ in range(20):b._dispatch(calls.append,'wake')
  self.assertEqual(len(b.gui.messages),1);b._deliver()
  b._dispatch(calls.append,'wake');b._deliver();self.assertEqual(calls,['wake','wake'])
 def test_distinct_diagnostic_arguments_are_preserved(self):
  b=self.make();calls=[];b._dispatch(calls.append,1);b._dispatch(calls.append,2)
  b._deliver();self.assertEqual(calls,[1,2]);self.assertEqual(len(b.gui.messages),1)
 def test_closed_receiver_drops_pending_and_new_deliveries(self):
  b=self.make();calls=[];b._dispatch(calls.append,1);b.closed=True
  b._deliver();b._dispatch(calls.append,2)
  self.assertFalse(calls);self.assertFalse(b.pending)
