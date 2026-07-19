from __future__ import annotations
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
from argus_m4_hello_nginx_cutover import CutoverError,target_compose  # noqa: E402
class CutoverTest(unittest.TestCase):
 def test_strips_loopback_port_from_minimal_target(self):
  source={'services':{'web':{'image':'nginx:stable','ports':[{'host_ip':'127.0.0.1','target':80}]}}}
  self.assertEqual({'name':'hello-nginx','services':{'web':{'image':'nginx:stable'}}},target_compose(source))
 def test_refuses_extra_service_or_source_mount(self):
  with self.assertRaises(CutoverError): target_compose({'services':{'web':{'image':'x'},'extra':{'image':'y'}}})
  with self.assertRaises(CutoverError): target_compose({'services':{'web':{'image':'x','volumes':['/:/host']}}})
