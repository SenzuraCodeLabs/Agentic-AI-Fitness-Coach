"""Generate resources/jargon_map.json.

Real gym vocabulary mapped to standardised terms so downstream extraction and
retrieval see one canonical spelling. Kept as data, not code, so the dictionary
can grow from the OOV candidates file without a code change.
"""

import json

J: dict[str, str] = {}


def add(canonical: str, *variants: str) -> None:
    for v in variants:
        J[v.lower()] = canonical


# --- Exercises: barbell ---------------------------------------------------
add("barbell back squat", "bb squat", "back squat", "squats", "squat", "squatted", "squatting")
add("barbell front squat", "front squat", "fs", "front squats")
add("barbell bench press", "bench", "bench press", "bp", "flat bench", "benching", "benched")
add("incline barbell bench press", "incline bench", "incline press", "incline bp")
add("decline barbell bench press", "decline bench", "decline press")
add(
    "conventional deadlift",
    "deadlift",
    "dl",
    "deads",
    "deadlifts",
    "conventional dl",
    "deadlifted",
    "deadlifting",
    "pulled",
)
add("sumo deadlift", "sumo", "sumo dl", "sumo deads")
add("romanian deadlift", "rdl", "rdls", "romanian dl", "stiff leg deadlift", "sldl")
add("overhead press", "ohp", "military press", "strict press", "shoulder press", "pressed")
add("push press", "push press", "pp")
add("barbell row", "bb row", "bent over row", "bor", "pendlay row", "barbell rows")
add("hip thrust", "hip thrusts", "ht", "barbell hip thrust")
add("good morning", "good mornings", "gm", "goodmornings")
add("power clean", "power cleans", "pc")
add("clean and jerk", "c&j", "cj")
add("snatch", "snatches")
add("hang clean", "hang cleans", "hc")
add("thruster", "thrusters")
add("zercher squat", "zercher", "zerchers")
add("box squat", "box squats")
add("pause squat", "pause squats", "paused squat")
add("safety bar squat", "ssb squat", "ssb", "safety squat bar")
add("hack squat", "hack squats")
add("split squat", "split squats", "bulgarian split squat", "bss", "bulgarians")
add("lunge", "lunges", "walking lunge", "walking lunges")
add("step up", "step ups", "stepups")

# --- Exercises: dumbbell / machine / bodyweight ---------------------------
add("dumbbell bench press", "db bench", "db press", "dumbbell press", "db bp")
add("dumbbell row", "db row", "db rows", "one arm row", "single arm row")
add("dumbbell fly", "db fly", "flyes", "flies", "chest fly", "pec fly")
add("lateral raise", "lat raise", "side raise", "lateral raises")
add("front raise", "front raises")
add("rear delt fly", "rear delt", "reverse fly", "rear delt flyes", "rear flies")
add("bicep curl", "curls", "bicep curls", "biceps curl", "db curl", "bb curl")
add("hammer curl", "hammer curls", "hammers")
add("preacher curl", "preacher curls", "preachers")
add("tricep extension", "tricep ext", "skullcrusher", "skullcrushers", "skulls")
add("tricep pushdown", "pushdown", "pushdowns", "rope pushdown", "cable pushdown")
add("lat pulldown", "pulldown", "pulldowns", "lat pull", "lat pulldowns")
add("seated cable row", "cable row", "seated row", "cable rows")
add("leg press", "leg presses")
add("leg extension", "leg ext", "leg extensions", "quad extension")
add("leg curl", "leg curls", "hamstring curl", "ham curl", "lying leg curl")
add("calf raise", "calf raises", "standing calf raise", "seated calf raise")
add("pull up", "pullup", "pullups", "pull ups", "chins", "chin up", "chinups", "pulling up")
add("push up", "pushup", "pushups", "push ups", "press up", "pressups")
add("dip", "dips", "tricep dips", "chest dips")
add("plank", "planks", "front plank")
add("hanging leg raise", "hlr", "leg raises", "hanging leg raises")
add("face pull", "face pulls", "facepulls")
add("shrug", "shrugs", "barbell shrug", "db shrug")
add("pec deck", "pec deck", "chest flye machine")
add("chest supported row", "csr", "chest supported rows")
add("nordic curl", "nordics", "nordic curls")
add("back extension", "back ext", "hyperextension", "hyperextensions")
add("glute bridge", "glute bridges")
add("farmers walk", "farmers carry", "farmers walks", "farmer walk")
add("kettlebell swing", "kb swing", "kb swings", "swings")
add("turkish get up", "tgu", "turkish getup")
add("goblet squat", "goblet squats", "goblets")
add("landmine press", "landmine", "landmine presses")
add("cable crossover", "crossover", "crossovers", "cable fly")
add("upright row", "upright rows")
add("pullover", "pullovers", "db pullover")

# --- Equipment ------------------------------------------------------------
add("barbell", "bb", "bar")
add("dumbbell", "db", "dbs", "dumbell", "dumbells")
add("kettlebell", "kb", "kbs", "kettlebells")
add("smith machine", "smith")
add("cable machine", "cables", "cable")
add("resistance band", "bands", "band", "resistance bands")
add("trap bar", "hex bar", "hexbar")
add("ez bar", "ez curl bar", "ezbar")
add("weight plate", "plates", "plate")

# --- Muscles / body parts -------------------------------------------------
add("deltoids", "delts", "delt", "shoulders", "front delts", "side delts")
add("latissimus dorsi", "lats", "lat")
add("quadriceps", "quads", "quad")
add("hamstrings", "hammies", "hams", "hamstring")
add("gluteus maximus", "glutes", "glute")
add("pectorals", "pecs", "pec", "chest")
add("trapezius", "traps", "trap")
add("biceps", "bis", "guns")
add("triceps", "tris")
add("abdominals", "abs", "core", "six pack")
add("erector spinae", "spinal erectors", "lower back", "erectors")
add("gastrocnemius", "calf", "calves")
add("forearms", "forearm", "grip")
add("rotator cuff", "cuff", "rotator")
add("adductors", "adductor", "inner thigh")
add("abductors", "abductor", "outer thigh")
add("rhomboids", "rhomboid", "upper back")
add("serratus anterior", "serratus")

# --- Intensity / effort metrics ------------------------------------------
add("rate of perceived exertion", "rpe")
add("reps in reserve", "rir")
add("one rep maximum", "1rm", "one rep max", "1 rep max", "maxes")
add("three rep maximum", "3rm", "three rep max")
add("five rep maximum", "5rm", "five rep max")
add("personal record", "pr", "prs", "personal best", "pb", "pbs")
add("as many reps as possible", "amrap")
add("every minute on the minute", "emom")
add("time under tension", "tut")
add("percentage of one rep max", "pct 1rm", "percent 1rm")
add("repetitions", "reps", "rep", "repetition")
add("sets", "set", "working sets")
add("working set", "work set", "top set")
add("warm up set", "warmup", "warm up", "warmups")
add("back off set", "backoff", "back off", "backoff set")
add("drop set", "dropset", "dropsets", "drop sets")
add("superset", "supersets")
add("giant set", "giant sets")
add("rest pause", "rest-pause", "restpause", "rp set")
add("cluster set", "cluster sets", "clusters")
add("myo reps", "myoreps", "myo-reps")
add("tempo", "eccentric tempo")
add("eccentric", "negatives", "negative", "eccentrics")
add("concentric", "positive")
add("isometric", "isometrics", "iso hold")

# --- Programming ----------------------------------------------------------
add("deload", "deloading", "deload week", "back off week")
add("periodisation", "periodization")
add("linear progression", "lp progression", "linear prog")
add("double progression", "double prog")
add("progressive overload", "overload", "progressive overload")
add("training volume", "volume")
add("training intensity", "intensity")
add("training frequency", "frequency")
add("hypertrophy", "size", "mass")
add("strength", "strength phase", "strength block")
add("mesocycle", "meso", "mesocycles", "block")
add("macrocycle", "macro cycle", "macrocycles")
add("microcycle", "micro cycle", "microcycles")
add("push pull legs", "ppl")
add("upper lower split", "upper lower", "ul split")
add("full body", "fullbody", "full body split")
add("bro split", "brosplit", "bro-split")
add("german volume training", "gvt", "10x10")
add("five by five", "5x5", "stronglifts", "starting strength")
add("wendler 531", "531", "wendler")
add("texas method", "texas method")
add("conjugate method", "conjugate", "westside")
add("daily undulating periodisation", "dup")
add("training max", "tm")
add("accessory work", "accessories", "accessory", "assistance work")
add("compound movement", "compounds", "compound", "big lifts")
add("isolation movement", "isolation", "isos", "isolations")
add("total tonnage", "tonnage", "volume load")

# --- Nutrition / body composition ----------------------------------------
add("macronutrients", "macros", "macro")
add("calories", "cals", "kcal", "calorie")
add("carbohydrates", "carbs", "carb")
add("caloric deficit", "cutting", "cut", "deficit", "shredding")
add("caloric surplus", "bulking", "bulk", "surplus", "lean bulk")
add("maintenance calories", "maintenance", "tdee")
add("body fat percentage", "bf%", "body fat")
add("recomposition", "recomp", "body recomp")
add("intermittent fasting", "fasting", "16:8")
add("creatine monohydrate", "creatine", "mono")
add("whey protein", "whey", "protein shake", "shake")
add("pre workout", "preworkout", "pre-workout", "pwo")
add("branched chain amino acids", "bcaa", "bcaas")
add("electrolytes", "electrolyte", "salts")

# --- Recovery / physiology ------------------------------------------------
add("delayed onset muscle soreness", "doms", "soreness")
add("central nervous system", "cns", "cns fatigue")
add("range of motion", "rom", "full rom", "partial rom")
add("mind muscle connection", "mmc", "mind-muscle")
add("muscle protein synthesis", "mps")
add("rest interval", "rest times", "rest period")
add("mobility work", "mobility", "stretching", "flexibility")
add("foam rolling", "foam roll", "smr", "myofascial release")
add("active recovery", "active rest", "recovery day")
add("overtraining", "overtrained", "overreaching")
add("form breakdown", "technical failure")
add("muscular failure", "failure", "to failure", "training to failure")
add("spotter", "spot", "spotting")
add("lockout", "lock out", "lockouts")
add("sticking point", "weak point")
add("bracing", "brace", "valsalva")
add("hip hinge", "hinge", "hip hinging")
add("knee valgus", "knees caving", "valgus")
add("butt wink", "buttwink")

# --- Units and misc -------------------------------------------------------
add("kilograms", "kg", "kgs", "kilos", "kilo")
add("pounds", "lb", "lbs", "pound")
add("gym session", "sesh", "session", "workout", "training session")
add("bar speed", "velocity")
add("beginner", "newbie", "novice")
add("intermediate lifter", "intermediate")
add("advanced lifter", "advanced")
add("natural lifter", "natty")

# Every canonical term maps to itself. Without this a canonical form that
# contains a shorter key as a prefix gets partially re-expanded: "lat pulldown"
# was becoming "latissimus dorsi pulldown" because "lat" matched and the full
# phrase was not itself a key. Self-mapping makes expansion idempotent, since
# the leftmost-longest rule then prefers the complete term.
for canonical in list(J.values()):
    J.setdefault(canonical.lower(), canonical)

out = {
    "_comment": (
        "Gym jargon -> standardised term. Matched with a single Aho-Corasick "
        "automaton in L3, one O(n) pass over the input. Canonical terms map to "
        "themselves so expansion is idempotent."
    ),
    "_generated_by": "scripts/gen_jargon.py",
    "_entry_count": len(J),
    "map": dict(sorted(J.items())),
}

with open("services/agent1_gatekeeper/resources/jargon_map.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)

print(f"jargon entries: {len(J)}  canonical terms: {len(set(J.values()))}")
