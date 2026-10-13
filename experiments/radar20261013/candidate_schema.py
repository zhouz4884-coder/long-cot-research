"""Gold-free scalar eligibility and exact candidate grouping."""
import time
from reason_transition.core import last_box, normalize_math_surface


def scalar_schema(text):
    start=time.perf_counter()
    try:
        from math_verify import parse, LatexExtractionConfig, ExprExtractionConfig
        from sympy import Expr, Float, Rational, cancel
        value=last_box(text)
        if value is None:
            return {'valid':False,'key':None,'reason':'incomplete_box','schema_ms':1000*(time.perf_counter()-start)}
        parsed=parse(r'\boxed{'+normalize_math_surface(value)+'}',
                     extraction_config=(LatexExtractionConfig(),ExprExtractionConfig()),parsing_timeout=2)
        obj=parsed[0] if parsed else None
        valid=isinstance(obj,Expr) and not obj.free_symbols and obj.is_number is True and obj.is_finite is True
        key=None
        if valid:
            exact=obj.xreplace({x:Rational(str(x)) for x in obj.atoms(Float)})
            key=str(cancel(exact))
        return {'valid':bool(valid),'key':key,'reason':None if valid else 'not_finite_constant_scalar',
                'schema_ms':1000*(time.perf_counter()-start)}
    except Exception as ex:
        return {'valid':False,'key':None,'reason':type(ex).__name__,
                'schema_ms':1000*(time.perf_counter()-start)}
