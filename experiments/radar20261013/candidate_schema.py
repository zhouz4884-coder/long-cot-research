"""Gold-free strict scalar eligibility and conservative canonical grouping."""
import time
from reason_transition.core import last_box, normalize_math_surface
from stem_quality import numeric_gold_issues


def scalar_schema(text):
    start=time.perf_counter()
    try:
        from math_verify import parse, LatexExtractionConfig, ExprExtractionConfig
        from sympy import Expr, Float, Rational, srepr
        value=last_box(text)
        if value is None:
            return {'valid':False,'key':None,'reason':'incomplete_box','schema_ms':1000*(time.perf_counter()-start)}
        surface=normalize_math_surface(value)
        # A numeric parse can be only a fragment of a prose/family answer.
        # The same syntax restriction is applied here to candidate text alone.
        issues=numeric_gold_issues(surface)
        if len(surface)>256 or issues:
            return {'valid':False,'key':None,'reason':'candidate_not_pure_numeric_surface',
                    'schema_ms':1000*(time.perf_counter()-start)}
        parsed=parse(r'\boxed{'+surface+'}',
                     extraction_config=(LatexExtractionConfig(),ExprExtractionConfig()),parsing_timeout=2)
        obj=parsed[0] if parsed else None
        valid=isinstance(obj,Expr) and not obj.free_symbols and obj.is_number is True and obj.is_finite is True
        key=None
        if valid:
            exact=obj.xreplace({x:Rational(str(x)) for x in obj.atoms(Float)})
            # Do not run unbounded algebraic cancellation in an online callback.
            # This is a structural canonical key; unequal keys do not establish
            # mathematical disagreement. Equal keys establish identical values.
            key=srepr(exact)
        return {'valid':bool(valid),'key':key,'reason':None if valid else 'not_finite_constant_scalar',
                'schema_ms':1000*(time.perf_counter()-start)}
    except Exception as ex:
        return {'valid':False,'key':None,'reason':type(ex).__name__,
                'schema_ms':1000*(time.perf_counter()-start)}
