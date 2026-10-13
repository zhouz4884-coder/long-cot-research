"""Predeclared text-only exclusions, independent of solver outputs or gold."""
import re


def numeric_gold_issues(gold):
    """Reject partial-number extraction from prose, families, sets or relations."""
    text=str(gold).strip()
    text=re.sub(r'^\$+|\$+$','',text).strip()
    allowed={'frac','dfrac','tfrac','sqrt','binom','cdot','times','div','pi','left','right',
             'sin','cos','tan','cot','sec','csc','log','ln','exp','arcsin','arccos','arctan'}
    commands=re.findall(r'\\([A-Za-z]+)',text)
    if any(c not in allowed for c in commands):return ['gold_not_pure_numeric_expression:unsupported_command_or_prose']
    bare=re.sub(r'\\[A-Za-z]+','',text)
    bare=re.sub(r'\\[,!; ]','',bare)
    if re.search(r'[A-Za-z]',bare):return ['gold_not_pure_numeric_expression:bare_letters_or_conditions']
    if ',' in bare and not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?',bare):
        return ['gold_not_pure_numeric_expression:list_or_multiple_values']
    if re.search(r'[=<>≤≥∈]|\b(?:and|or)\b',bare):return ['gold_not_pure_numeric_expression:relation']
    if not re.fullmatch(r'[\d\s+\-−*/^{}()\[\].,%_|π√\\]+',bare):
        return ['gold_not_pure_numeric_expression:unsupported_surface']
    return []


def stem_issues(question,subject):
    issues=[]
    if re.search(r'\b(estimate|estimation)\b',question,re.I):
        issues.append('estimation_or_partial_credit_task_not_exact_scalar_accuracy')
    if re.search(r'\b(figure|diagram|pictured|image|as shown|shown below|shown above)\b',question,re.I):
        issues.append('visual_reference_without_provided_image')
    if subject!='Geometry':return issues
    # A conservative explicit-label screen. It is not a proof of well-posedness.
    setup=re.split(r'\b(find|what is|compute|calculate|determine)\b',question,flags=re.I)[0]
    math_segments=re.findall(r'\$([^$]+)\$',question)
    used=set();introduced=set()
    for segment in math_segments:
        clean=re.sub(r'\\[A-Za-z]+',' ',segment)
        used.update(re.findall(r'[A-Z]',clean))
        # Individually named points or a comma-separated named-point list.
        introduced.update(re.findall(r'(?<![A-Z])[A-Z](?![A-Z])',clean))
    for match in re.finditer(r'(?:triangle|\\triangle)\s*\$?([A-Z](?:\s*[A-Z]){2})',setup,re.I):
        introduced.update(re.findall(r'[A-Z]',match.group(1)))
    missing=sorted(used-introduced)
    if missing:issues.append('geometry_labels_without_explicit_introduction:'+','.join(missing))
    return issues
