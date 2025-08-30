from letta_client import Letta

client = Letta(
    token="sk-let-OWQ2NGNjOGUtOTY2NS00ODRiLWI3YzQtMzY0Zjg4ODE4MTA3OjBlMmRhMTI5LTFkOTgtNDNkYi05MmNmLWFjYzc4MGY0NTQ4ZQ==",
    project="default-project",
)
client = Letta()
response = client.agents.messages.create(
    agent_id="agent-addb431d-4bb8-4c6f-a9c7-ef08947ba73a",
    messages=[
        {
            "role": "user",
            "content": "Hey, nice to meet you, my name is Brad."
        }
    ]
)

agent = client.agents.summarize_agent_conversation()

# the agent will think, then edit its memory using a tool
for message in response.messages:
    print(message.content)





