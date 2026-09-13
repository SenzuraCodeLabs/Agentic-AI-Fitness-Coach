"""Exercise-science evidence corpus.

Every chunk carries a source attribution so a coaching claim can be traced to
the guidance it came from. Grounding is the whole point of the retrieval step:
without citations the coach is just an LLM asserting things about training.

The content paraphrases established position stands and review findings. It is
deliberately conservative and general, and no chunk gives medical advice.
"""

from __future__ import annotations

CORPUS: list[dict[str, str]] = [
    {
        "id": "activity-001",
        "topic": "cardio aerobic activity",
        "source": "CDC, Adult Activity: An Overview",
        "url": "https://www.cdc.gov/physical-activity-basics/guidelines/adults.html",
        "text": (
            "Adults should aim for at least 150 minutes of moderate-intensity "
            "aerobic activity per week, or 75 minutes of vigorous activity, "
            "alongside muscle-strengthening activity on at least two days. "
            "Activity can be spread across the week."
        ),
    },
    {
        "id": "bands-001",
        "topic": "equipment resistance bands home training",
        "source": "Lopes et al. (2019), elastic versus conventional resistance meta-analysis",
        "url": "https://pubmed.ncbi.nlm.nih.gov/30815258/",
        "text": (
            "A systematic review found similar strength improvements with elastic "
            "resistance and conventional resistance equipment. Resistance bands "
            "are a practical training option when machines or free weights are "
            "unavailable; the evidence does not imply that every exercise is "
            "interchangeable."
        ),
    },
    {
        "id": "failure-001",
        "topic": "training to failure",
        "source": "Grgic et al. (2022), failure versus non-failure meta-analysis",
        "url": "https://pubmed.ncbi.nlm.nih.gov/33497853/",
        "text": (
            "Training every set to repetition failure is not required for gains "
            "in strength or muscle size. This meta-analysis found no significant "
            "overall difference between failure and non-failure training for "
            "those outcomes; study populations and protocols limit "
            "generalisation."
        ),
    },
    {
        "id": "sleep-002",
        "topic": "sleep recovery",
        "source": "CDC, About Sleep",
        "url": "https://www.cdc.gov/sleep/about/",
        "text": (
            "Adults aged 18 to 60 generally need at least seven hours of sleep "
            "each night. Sleep quality also matters. A consistent sleep schedule "
            "is a useful part of a recovery routine; sleep duration alone cannot "
            "determine readiness to increase a training load."
        ),
    },
    {
        "id": "acsm-001",
        "topic": "progression stalling plateau",
        "source": "ACSM (2009), Progression Models in Resistance Training for Healthy Adults",
        "url": "https://pubmed.ncbi.nlm.nih.gov/19204579/",
        "text": (
            "Progression should reflect the individual's goal, capacity and "
            "training experience. ACSM recommends increasing load by 2 to 10 "
            "percent when the current workload can be performed for one or two "
            "repetitions beyond the desired number. A stalled load by itself does "
            "not establish that a heavier weight is appropriate."
        ),
    },
    {
        "id": "rir-accuracy-001",
        "topic": "RPE RIR accuracy effort",
        "source": "Halperin et al. (2022), predicting repetitions to task failure",
        "url": "https://pubmed.ncbi.nlm.nih.gov/34542869/",
        "text": (
            "Repetitions-in-reserve estimates are subjective rather than exact "
            "measurements. Research on predicting repetitions to task failure "
            "finds variable accuracy. Treat RPE and RIR as context alongside "
            "completed reps, load and technique, rather than as precise "
            "guarantees."
        ),
    },
    {
        "id": "vol-001",
        "topic": "training volume",
        "source": "Schoenfeld et al. (2017), Journal of Sports Sciences",
        "text": (
            "Weekly set volume per muscle group shows a dose-response relationship "
            "with hypertrophy. Roughly 10 to 20 hard sets per muscle group per week "
            "suits most trained lifters, with returns diminishing beyond that and "
            "recovery becoming the limiting factor."
        ),
    },
    {
        "id": "vol-002",
        "topic": "training volume",
        "source": "ACSM Position Stand on Progression Models (2009)",
        "text": (
            "Novice lifters progress well on 1 to 3 sets per exercise, while "
            "intermediate and advanced lifters generally need multiple sets with "
            "systematic variation in volume and intensity to keep adapting."
        ),
    },
    {
        "id": "int-001",
        "topic": "training intensity",
        "source": "ACSM Position Stand on Progression Models (2009)",
        "text": (
            "Loads of 60 to 70 percent of one-rep maximum suit novices building "
            "strength, while advanced lifters typically use 80 to 100 percent for "
            "maximal strength. Hypertrophy responds across a wide range provided "
            "sets are taken close to failure."
        ),
    },
    {
        "id": "int-002",
        "topic": "rep ranges",
        "source": "Schoenfeld, Grgic et al. (2021), meta-analysis",
        "text": (
            "Hypertrophy is similar across rep ranges from about 6 to 30 when sets "
            "are taken near failure. Strength gains are more load-specific and "
            "favour heavier loads in lower rep ranges."
        ),
    },
    {
        "id": "prog-001",
        "topic": "progressive overload",
        "source": "Kraemer and Ratamess (2004), Medicine and Science in Sports",
        "text": (
            "Progressive overload requires a gradual increase in training stress "
            "over time. It can be applied by adding load, adding reps, adding sets, "
            "increasing frequency, reducing rest, or improving movement quality at "
            "the same load."
        ),
    },
    {
        "id": "prog-002",
        "topic": "progressive overload",
        "source": "Practical loading guidance, NSCA Essentials",
        "text": (
            "A common practical increment is 2.5 to 5 percent added to the working "
            "load once the top of the target rep range is reached on all prescribed "
            "sets with acceptable technique. Upper-body lifts usually progress in "
            "smaller absolute jumps than lower-body lifts."
        ),
    },
    {
        "id": "prog-003",
        "topic": "double progression",
        "source": "Practical programming guidance",
        "text": (
            "Double progression adds reps within a range before adding load. "
            "Working from 3 sets of 8 up to 3 sets of 12, then increasing the "
            "weight and returning to 8, keeps progression steady when load jumps "
            "would be too large."
        ),
    },
    {
        "id": "rpe-001",
        "topic": "RPE and RIR",
        "source": "Zourdos et al. (2016), Journal of Strength and Conditioning",
        "text": (
            "Repetitions-in-reserve based RPE gives a reliable estimate of "
            "proximity to failure in resistance training. RPE 8 corresponds to "
            "roughly 2 reps in reserve, and RPE 10 to genuine momentary failure."
        ),
    },
    {
        "id": "rpe-002",
        "topic": "autoregulation",
        "source": "Helms et al. (2018), Strength and Conditioning Journal",
        "text": (
            "Autoregulating load against daily RPE accounts for fluctuations in "
            "readiness. If a prescribed load feels harder than the target RPE, "
            "reducing it that day preserves the intended training stimulus better "
            "than grinding through."
        ),
    },
    {
        "id": "del-001",
        "topic": "deload",
        "source": "Bell et al. (2022), review of fatigue management",
        "text": (
            "Planned reductions in volume or intensity every 4 to 8 weeks help "
            "dissipate accumulated fatigue. Common approaches halve the volume or "
            "hold the load near 60 to 70 percent of usual working weights for one "
            "week."
        ),
    },
    {
        "id": "del-002",
        "topic": "stalling",
        "source": "Practical programming guidance",
        "text": (
            "When a lift stalls for two to three consecutive sessions despite "
            "adequate sleep and nutrition, the usual responses are a short deload, "
            "a reduction in volume, or a change of exercise variation rather than "
            "simply trying harder."
        ),
    },
    {
        "id": "freq-001",
        "topic": "training frequency",
        "source": "Schoenfeld, Ogborn and Krieger (2016), Sports Medicine",
        "text": (
            "Training a muscle group twice per week produces greater hypertrophy "
            "than once per week when total volume is equated. Beyond twice weekly "
            "the added benefit is small if volume is held constant."
        ),
    },
    {
        "id": "rest-001",
        "topic": "rest intervals",
        "source": "Grgic et al. (2018), Sports Medicine",
        "text": (
            "Rest intervals longer than two minutes between sets support greater "
            "strength and hypertrophy outcomes than short rests, because they "
            "preserve performance across working sets."
        ),
    },
    {
        "id": "prot-001",
        "topic": "protein intake",
        "source": "Morton et al. (2018), British Journal of Sports Medicine",
        "text": (
            "Protein intake of roughly 1.6 grams per kilogram of body mass per day "
            "supports resistance-training adaptations, with little added benefit "
            "beyond about 2.2 grams per kilogram."
        ),
    },
    {
        "id": "tech-001",
        "topic": "squat technique",
        "source": "NSCA technique guidance",
        "text": (
            "In the back squat, the bar should track over the midfoot, the torso "
            "angle should stay consistent through the ascent, and the knees should "
            "track in line with the toes. Depth is limited by hip structure and "
            "ankle mobility, and forcing depth beyond a neutral spine is "
            "counterproductive."
        ),
    },
    {
        "id": "tech-002",
        "topic": "deadlift technique",
        "source": "NSCA technique guidance",
        "text": (
            "In the conventional deadlift the bar starts over the midfoot and stays "
            "close to the body throughout. The lift begins with the hips and "
            "shoulders rising together; the hips rising first turns the movement "
            "into a stiff-legged pull and shifts load to the lower back."
        ),
    },
    {
        "id": "tech-003",
        "topic": "bench press technique",
        "source": "NSCA technique guidance",
        "text": (
            "In the bench press, retracting and depressing the shoulder blades "
            "creates a stable base and reduces shoulder stress. The bar typically "
            "touches around the lower chest and travels in a slight arc back over "
            "the shoulders at lockout."
        ),
    },
    {
        "id": "warm-001",
        "topic": "warm up",
        "source": "Practical guidance, NSCA Essentials",
        "text": (
            "An effective warm-up raises tissue temperature with light general "
            "activity, then works up to the first working set through several "
            "ascending sets, keeping reps low as the load approaches the working "
            "weight so fatigue is not accumulated before it counts."
        ),
    },
    {
        "id": "beg-001",
        "topic": "beginner progression",
        "source": "Practical programming guidance",
        "text": (
            "Beginners can often add load every session because neural adaptation "
            "is rapid. Linear progression typically continues for several months "
            "before session-to-session increments become unsustainable and weekly "
            "or block progression is needed."
        ),
    },
    {
        "id": "sleep-001",
        "topic": "recovery",
        "source": "Dattilo et al. (2011), review of sleep and recovery",
        "text": (
            "Insufficient sleep impairs recovery and reduces training performance. "
            "Seven to nine hours supports the hormonal environment and tissue "
            "repair that resistance training depends on."
        ),
    },
]
