"""Gold-free strict scalar eligibility and conservative canonical grouping."""
import re
import time
from reason_transition.core import last_box, normalize_math_surface
from stem_quality import numeric_gold_issues


def candidate_surface_issues(surface):
    """Candidate-only postfix factorial support; frozen data eligibility stays.

    The earlier whitelist rejected the observed valid1/7! answer. Permit only
    a single postfix factorial in numeric syntax, then require Math-Verify to
    produce a finite constant. Prose, relations and partial families still fail.
    """
    runs=list(re.finditer(r'(?<!\\)!+',surface))
    for match in runs:
        left=surface[:match.start()].rstrip();right=surface[match.end():].lstrip()
        if len(match.group())!=1 or not left or left[-1] not in '0123456789)}]':
            return ['candidate_invalid_factorial_syntax']
        if right and right[0] not in '+-*/^)}]':
            if not re.match(r'\\(?:cdot|times|div|right)(?![A-Za-z])',right):
                return ['candidate_invalid_factorial_syntax']
    sanitized=re.sub(r'(?<!\\)!','',surface)
    return numeric_gold_issues(sanitized)


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
        issues=candidate_surface_issues(surface)
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
