"""Bounded recursive context reducer; RLM-inspired prototype, no code execution."""
class BudgetExceeded(ValueError):pass
class RecursiveContext:
    def __init__(self,model,chunk_chars=6000,max_chars=96000,max_calls=24,max_depth=6):
        self.model=model;self.chunk_chars=chunk_chars;self.max_chars=max_chars;self.max_calls=max_calls;self.max_depth=max_depth
        if chunk_chars<100 or max_calls<1:raise ValueError('Invalid limits')
    def run(self,question,text):
        if len(text)>self.max_chars:raise BudgetExceeded('Input limit exceeded')
        calls=0;trace=[]
        def visit(start,end,depth):
            nonlocal calls
            if depth>self.max_depth:raise BudgetExceeded('Recursion depth exceeded')
            if end-start>self.chunk_chars:
                middle=(start+end)//2
                left=visit(start,middle,depth+1);right=visit(middle,end,depth+1)
                data={'children':[left,right]}
            else:data={'source_span':[start,end],'source_text':text[start:end]}
            if calls>=self.max_calls:raise BudgetExceeded('Model call limit exceeded')
            calls+=1
            result=self.model(question,data)
            if not isinstance(result,str) or len(result)>4000:raise ValueError('Model output exceeds bounded result size')
            trace.append({'call':calls,'depth':depth,'source_span':[start,end]})
            return {'finding':result,'source_span':[start,end]}
        result=visit(0,len(text),0)
        return {'result':result,'trace':trace,'calls':calls,'source_chars':len(text)}
