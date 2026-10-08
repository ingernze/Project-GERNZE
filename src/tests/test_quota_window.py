import tkinter as tk
import unittest
from quota_card import QuotaCard, CardState

class WindowTests(unittest.TestCase):
 def test_create_click_feedback_disabled_and_close(self):
  root=tk.Tk(); root.withdraw(); calls=[]
  c=QuotaCard(root,on_save=lambda v:None,on_delete=lambda:None,on_toggle=lambda:calls.append('toggle'),on_refresh=lambda:calls.append('refresh'),on_close=lambda:c.withdraw())
  try:
   c.render(CardState(key_present=True,enabled=True,demo=True));root.update()
   c.refresh_button.invoke(); self.assertEqual(calls,['refresh']);root.update()
   c.render(CardState(key_present=True,enabled=True,cooldown_remaining=300,demo=True))
   self.assertTrue(c.refresh_button.instate(['disabled']))
   c.refresh_button.invoke();c._refresh();self.assertEqual(calls,['refresh'])
   c.toggle_button.activate();self.assertEqual(calls[-1],'toggle')
   c.open_key_manager(); d=c._key_dialog; d._key_var.set('offline-example')
   self.assertEqual(c.key_entry.cget('show'),'●')
   c._on_close();root.update();self.assertEqual(c.state(),'withdrawn')
   self.assertFalse(d.winfo_exists());self.assertEqual(d._key_var.get(),'')
  finally:root.destroy()
