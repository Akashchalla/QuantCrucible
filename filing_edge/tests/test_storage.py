import unittest
from unittest.mock import MagicMock,patch
from edge.storage import persist_dataset

class StorageTests(unittest.TestCase):
    def test_refresh_uses_a_separate_autocommit_connection(self):
        insert,refresh=MagicMock(),MagicMock()
        insert.__enter__.return_value=insert;refresh.__enter__.return_value=refresh
        order=[]
        insert.__exit__.side_effect=lambda *args:order.append('insert committed') or False
        refresh.execute.side_effect=lambda *args:order.append('refresh executed')
        with patch('edge.storage.connect',side_effect=[insert,refresh]):
            persist_dataset({'kind':'massive','observations':[]})
        self.assertEqual(order,['insert committed','refresh executed'])
        self.assertTrue(refresh.autocommit)
        refresh.execute.assert_called_once_with("CALL refresh_continuous_aggregate('daily_option_activity', NULL, NULL)")
