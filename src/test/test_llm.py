from llm_openai import OpenAIResponsesLLM, LLMConfig   

cfg = LLMConfig(
    model="gpt-5",
    max_output_tokens=200
)

llm = OpenAIResponsesLLM(cfg)

messages = [
    {
        "role": "user",
        "content": "Say hello in one short sentence."
    }
]

tools = []  

resp = llm.responses_create(messages, tools)

print("===== RESPONSE =====")
print(resp)