"""Which areas will make model calls for a new message. Planners are plain code, so only reading ever calls the model."""

def predict():
    return {"model_call_areas": ["reading"], "max_model_calls": 1,
            "plain_code_areas": ["venue", "food", "judging", "schedule", "budget"],
            "text": "Model calls: reading only (1 call per message or file). "
                    "venue, food, judging, schedule and budget make no model calls; the affected ones re-run as plain code."}
