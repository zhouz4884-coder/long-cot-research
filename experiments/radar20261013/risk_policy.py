"""Pure past-observable policy rules, shared by replay and real execution."""
import math
import hashlib


def problem_shard(problem_id,shards):
    """Fix the physical worker from ID, independently of split membership/order."""
    assert isinstance(problem_id,str) and problem_id and isinstance(shards,int) and shards>0
    return int.from_bytes(hashlib.sha256(('gpu-shard:'+problem_id).encode()).digest()[:8],'big')%shards


def features_at(point,readout):
    from radar_engine import candidate_features
    features={**point['features'],**candidate_features(readout)}
    for group,key in [('cue_h','cue_projection'),('answer_h','answer_projection')]:
        if readout.get(key) is not None:
            features.update({f'{group}_{i}':v for i,v in enumerate(readout[key])})
    return features


def quality_decision(spec,prediction,schema_valid):
    if prediction['outside_length_support']:
        return 'FALLBACK'
    if not schema_valid:return 'DEFER'
    if spec['kind']=='current_correctness':
        return 'COMMIT' if prediction['candidate_correct']>=spec['correctness_threshold'] else 'DEFER'
    if spec['kind']=='risk_gate':
        permitted=(prediction['stop_harm_vs_action']<=spec['risk_threshold']
                   and prediction['candidate_correct']>=spec.get('minimum_correctness',0.))
        return 'COMMIT' if permitted else 'DEFER'
    raise ValueError('Unsupported pure quality policy: '+spec['kind'])


def eat_update(mean,variance,entropy,count):
    mean=.8*mean+.2*entropy
    variance=.8*variance+.2*(entropy-mean)**2
    return mean,variance,variance/(1-.8**count)


def deer_pro_confidence(readouts,penalty):
    scores=[r['maxprob_geomean'] for r in readouts]
    mean=sum(scores)/len(scores)
    mad=sum(abs(x-mean) for x in scores)/len(scores)
    return mean-penalty*mad


def conformal_dual_update(previous,confidence,offset,spec):
    """Independent paper-rule adaptation; this callback uses no labels.

    EMA semantics match the frozen helper: alpha weights the newest signal.
    The slope is dimensionless c*B; shift_fraction is relative to the declared
    reference cap. Risk calibration is a separate complete-policy operation.
    """
    assert math.isfinite(confidence) and 0<=confidence<=1
    assert 0<spec['ema_alpha']<=1 and 0<spec['upper_threshold']<=1
    assert 0<=spec['lower_base']<spec['upper_threshold']
    assert spec['slope_times_budget']>=0 and spec['reference_budget']>0
    assert offset>=0
    smoothed=confidence if previous is None else spec['ema_alpha']*confidence+(1-spec['ema_alpha'])*previous
    z=spec['slope_times_budget']*(offset/spec['reference_budget']-spec['shift_fraction'])
    logistic=1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))
    # At finite precision the lower curve can round to the upper value.
    # Keep strict ordering, including saturated long/short-horizon cases.
    upper=spec['upper_threshold']
    lower=min(math.nextafter(upper,-math.inf),spec['lower_base']+(upper-spec['lower_base'])*logistic)
    route='upper' if smoothed>=upper else 'lower' if smoothed<=lower else 'continue'
    return {'smoothed_confidence':smoothed,'lower_threshold':lower,'upper_threshold':upper,'route':route}


def conformal_discrete_losses(correctness,exit_index,route):
    """Offline Eq8-11 diagnostics on a declared discrete candidate trajectory.

    Upper error counts only upper-triggered wrong candidates; lower risk is
    the suffix correctness fraction. Neither equals harmful STOP vs FULL.
    Fallback has no threshold-triggered loss, even when FULL itself is wrong.
    These losses do not by themselves certify any policy.
    """
    y=list(correctness);assert y and set(y)<={0,1}
    n=len(y);assert 0<=exit_index<n and route in ['upper','lower','fallback']
    first=next((i for i,value in enumerate(y) if value),None)
    return {'upper_error':float(route=='upper' and not y[exit_index]),
            'lower_future_correctness':sum(y[exit_index:])/(n-exit_index) if route=='lower' else 0.,
            'upper_efficiency_regret':max(0,exit_index-first)/n if route=='upper' and first is not None else 0.,
            'lower_past_incorrect_fraction':sum(1-value for value in y[:exit_index+1])/n if route=='lower' else 0.,
            'harmful_vs_final':int(y[-1]==1 and y[exit_index]==0) if route!='fallback' else 0}


def bounded_family_ucb(problem_loss_rows,alpha):
    """Conditional IID Hoeffding family bound; rows are independent problems.

    Not a certificate for the current stratified calibration split. This helper
    is an explicit statistical sensitivity/adapter interface, never a substitute
    for the study's finite-design audit or the author method's assumptions.
    """
    rows=[list(row) for row in problem_loss_rows]
    assert rows and rows[0] and 0<alpha<1
    n=len(rows);k=len(rows[0]);assert all(len(row)==k for row in rows)
    assert all(math.isfinite(value) and 0<=value<=1 for row in rows for value in row)
    radius=math.sqrt(math.log(k/alpha)/(2*n))
    means=[sum(row[j] for row in rows)/n for j in range(k)]
    return {'independent_problem_rows':n,'candidate_count':k,'familywise_alpha':alpha,
            'empirical_losses':means,'finite_sample_radius':radius,
            'upper_bounds':[min(1.,value+radius) for value in means],
            'assumption':'Independent identically distributed bounded problem losses; not established by the frozen stratified split.'}
