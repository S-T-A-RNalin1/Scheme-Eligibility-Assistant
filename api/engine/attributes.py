"""The attribute registry: the only vocabulary rule trees may use.

Seeded into the `attribute_registry` collection; the profile wizard is generated from it.
"""
OCCUPATIONS = ["farmer", "agricultural_labourer", "student", "entrepreneur", "artisan", "weaver",
               "fisherman", "construction_worker", "street_vendor", "unorganised_worker",
               "salaried", "self_employed", "unemployed", "homemaker", "retired", "other"]

STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
    "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]

EDUCATION = ["none", "below_class_10", "class_10", "class_12", "diploma", "graduate", "postgraduate", "phd"]

ATTRIBUTES = [
    {"key": "age", "type": "number", "unit": "years", "min": 0, "max": 120, "question": "What is your age?"},
    {"key": "gender", "type": "enum", "options": ["male", "female", "transgender"], "question": "What is your gender?"},
    {"key": "state", "type": "enum", "options": STATES, "question": "Which state / UT do you live in?"},
    {"key": "area_type", "type": "enum", "options": ["rural", "urban"], "question": "Do you live in a rural or urban area?"},
    {"key": "category", "type": "enum", "options": ["General", "OBC", "SC", "ST", "EWS"], "question": "What is your social category?"},
    {"key": "annual_income", "type": "number", "unit": "INR / year", "min": 0, "question": "What is your annual family income (₹)?"},
    {"key": "occupation", "type": "enum", "options": OCCUPATIONS, "question": "What is your main occupation?"},
    {"key": "is_student", "type": "boolean", "question": "Are you currently a student?"},
    {"key": "education_level", "type": "enum", "options": EDUCATION, "question": "Highest education passed?"},
    {"key": "marks_percent", "type": "number", "unit": "%", "min": 0, "max": 100, "question": "Marks (%) in your last qualifying exam?"},
    {"key": "land_holding_hectares", "type": "number", "unit": "hectares", "min": 0, "question": "How much agricultural land do you own (hectares)?"},
    {"key": "is_bpl", "type": "boolean", "question": "Does your household hold a BPL card?"},
    {"key": "has_disability", "type": "boolean", "question": "Do you have a disability?"},
    {"key": "disability_percent", "type": "number", "unit": "%", "min": 0, "max": 100, "question": "Disability percentage (as certified)?"},
    {"key": "is_income_tax_payer", "type": "boolean", "question": "Are you (or have you been) an income-tax payer?"},
    {"key": "is_citizen", "type": "boolean", "question": "Are you an Indian citizen?"},
    {"key": "marital_status", "type": "enum", "options": ["unmarried", "married", "widowed", "divorced"], "question": "Marital status?"},
    {"key": "is_minority", "type": "boolean", "question": "Do you belong to a notified minority community?"},
]

BY_KEY = {a["key"]: a for a in ATTRIBUTES}
