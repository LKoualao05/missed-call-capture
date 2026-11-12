# Design Decisions

Short records of the choices that shaped the system and why.

## 1. Custom Python service instead of a no-code builder

Tools like GoHighLevel or Zapier can send a missed-call text. They get awkward once the conversation needs to branch on what the customer actually said, pull several answers out of one message, fall back when the AI fails, and enforce compliance rules. A small FastAPI service keeps all of that in testable code, runs every client from one deployment, and costs a few dollars a month to host.

## 2. Conditional forwarding is the default

Owners are attached to their number. It's on their trucks, yard signs, and Google profile. Conditional forwarding means nothing changes for them: their phone rings like always, and only the calls they miss reach Twilio. Front-number mode exists for businesses that already use a tracking number.

## 3. Three questions, configurable per trade

Three is the most a customer will reliably answer by text, and the minimum an owner needs to call back ready to quote: what's wrong, how soon, and where. The wording comes from the owner's own callback script during discovery, because generic questions produce leads the owner has to re-qualify.

## 4. The model proposes, the code decides

Claude is good at reading messy replies and terrible to trust with state. It returns structured output through a forced tool call. Code decides what counts as an answer, when the lead is complete, and what the closing text says. The owner-facing lead format never passes through the model. This keeps the output the owner sees identical across thousands of conversations.

## 5. Scripted fallback on every turn

A customer who texts back and hears nothing calls a competitor. If the Claude call errors, times out, or returns something unusable, `ScriptedQualifier` answers that turn using the next open question. Leads may come out less tidy, but they always come out.

## 6. Reply asynchronously to Twilio

Twilio's webhook timeout is 15 seconds and LLM latency varies. The SMS webhook returns empty TwiML immediately and sends the reply through the REST API from a background task.

## 7. Partial leads over silence

Some customers stop replying after one or two texts. A name, number, and "AC not cooling" is still a callable lead, so the cron sends whatever was collected after 20 minutes, clearly labeled as partial.

## 8. Emergencies interrupt the flow

Gas leaks and flooding can't wait for question three. The first mention, caught by the model or by a keyword list (keywords catch what the model misses), sends the owner an urgent alert right away and tells the customer to get safe and call 911.

## 9. SQLite

One region, a few dozen clients, a handful of writes per conversation. SQLite is one file, needs no server, and is easy to query during a support call. The store is behind a small class, so moving to Postgres is contained.

## 10. Never text someone who opted out

Twilio's Messaging Service blocks texts to numbers that replied STOP. The app also records opt-outs itself so it doesn't start a new conversation, burn an AI call, or log a failed send for someone who already said no.
