from app.agent.request import build_user_request
examples = ['Ishan should know that I\'ll call him later.', 'Could you pass a message to Ishan that I\'ll call him later?', 'Make sure Ishan gets the message that I\'ll call him later.', 'Please inform Ishan I\'ll call him later.', 'I need Ishan to know I\'ll call him later.', 'Get a message to Ishan saying I\'ll call him later.', 'Use the other AI site instead.', 'I need to check something in my browser.', 'Open the browser and find the FastAPI documentation.', 'Search the same thing there.']
ctx = {'current_browser': 'brave', 'last_query': 'FastAPI', 'current_window': 'ChatGPT', 'recent_turns': [], 'current_target': 'chatgpt'}
for text in examples:
    req = build_user_request(text, ctx)
    print('TEXT:', text)
    print(' ->', req.kind, req.intent, req.target, req.target_type, req.query, sorted(req.capabilities), [(e.kind, e.value) for e in req.entities])
    print('---')
