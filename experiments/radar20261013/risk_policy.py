"""Pure past-observable policy rules, shared by replay and real execution."""
import math


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
