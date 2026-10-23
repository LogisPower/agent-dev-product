import unittest
from recursive_context import RecursiveContext,BudgetExceeded
class Tests(unittest.TestCase):
 def test_bounds_and_spans(self):
  runner=RecursiveContext(lambda q,data:'finding',chunk_chars=100,max_chars=1000)
  result=runner.run('question','x'*300)
  self.assertEqual(result['calls'],7);self.assertEqual(result['result']['source_span'],[0,300])
  with self.assertRaises(BudgetExceeded):runner.run('question','x'*1001)
  with self.assertRaises(BudgetExceeded):RecursiveContext(lambda *a:'ok',chunk_chars=100,max_calls=2).run('q','x'*300)
if __name__=='__main__':unittest.main(verbosity=2)
