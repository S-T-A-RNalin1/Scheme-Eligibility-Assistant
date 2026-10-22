# Scheme Eligibility Assistant — Viva Guide

## 1. The project in one minute (say this first)

"Our project helps a person find out which government schemes they can get. They fill in a short form with age, income, state, caste category and so on. Our app then checks that profile against every scheme and says **Eligible**, **Not eligible**, or **Need more information**. For every answer it shows the exact condition that decided it.

We also have an **Ask** page. You type a question, like 'what documents do I need for Atal Pension Yojana?', and the answer comes only from the scheme text we stored, with the source shown. If we do not have the answer, it says so instead of guessing.

All data is stored in **MongoDB**. One important decision: **eligibility is decided by normal code, never by an AI model.** The AI part, if used, only explains."

## 2. The idea in easy words

**Problem.** Scheme rules are long and written differently for each scheme. People give up or pay agents.

**Our solution.**
1. We took 601 scheme pages (a public dataset from myScheme on Hugging Face) and cleaned them into **570 schemes**.
2. We turned each scheme's eligibility text into **rules stored as data**, for example "age between 18 and 40 AND NOT income-tax payer".
3. One small program, the **rules engine**, reads those rules and checks any profile.
4. If the user skipped a question, the result is **UNKNOWN**, not "rejected". The app then asks for that missing detail.
5. Every check is **saved with a copy of the rules and answers used**, plus a checksum, so it can be re-checked later and tampering shows up.

**Why MongoDB.** A scheme is one nested thing: text, benefits, documents, and a rule tree. In MongoDB it is one document, read in one go. In SQL it would need many tables and joins.

**Simple analogy.** The rules engine is like a checklist. Each scheme has its own checklist, and the engine ticks it against your answers. A box left blank is "don't know yet", not "no".

## 3. How it works step by step (for the demo)

1. **Data in:** PDFs → cleaned into sections → saved in MongoDB (`schemes`).
2. **Rules:** a script suggests rules from the eligibility text. A **validator** checks them (allowed questions only, quote really exists in the text, numbers match). Only rules a person has checked are published: I hand-checked 16 well-known schemes (in `data/curated_rules.json`), and the seed script publishes them.
3. **Publishing:** each approval creates a **new version** (old versions are never edited), saved inside a **transaction**.
4. **User checks eligibility:** the engine runs on all published schemes and saves one audit record per scheme.
5. **User asks a question:** it is sent to the right place. Eligibility questions go to the engine. Information questions go to search. Off-topic questions are refused. Search combines **keyword + meaning-based search**, and the answer must cite its sources.

## 4. Where MongoDB is used (ready answer)

- **12 collections:** schemes, scheme_versions, evaluations, document_chunks, users, user_profiles, attribute_registry, ingestion_jobs, chat_logs, rate_limits, grievances, counters.
- **CRUD:** create (register, checks), read (scheme list with search, paging), update (save profile with upsert), delete (delete my data, retire scheme).
- **Validators:** the database itself rejects bad data (e.g. verdict "MAYBE", negative age).
- **Indexes:** unique (slug, email), compound ({status, level, state} and {user_id, evaluated_at}), text, TTL.
- **Transaction:** publishing a rule version (insert version + update scheme + update job together).
- **Aggregation:** verdict counts, most-missing answers, schemes per state, user history.
- **TTL:** chat logs expire after 30 days, rate-limit counters expire in minutes.
- **Search:** `$text` index plus stored embeddings (256 numbers per text chunk).

## 5. Numbers to remember

| What | Number |
|---|---|
| PDFs downloaded | 601 |
| Unique schemes | 570 (113 central, 457 state, 34 states/UTs) |
| Schemes with hand-checked published rules | 16 |
| Rule conditions suggested automatically | 909 (502 of 570 trees passed validation) |
| Text chunks indexed | 3,991 |
| Automated tests | 114, all passing |
| Sample profiles with expected verdict | 35 of 35 correct |
| Eligibility check over all published schemes | about 5.5 ms |
| Index benefit | 5,906 records scanned → 15 to 391 with an index |
| Retrieval when scheme is named | Recall@5 = 1.00 (hybrid) |
| Retrieval when scheme is only described | hybrid 0.68, vector alone 0.82 |
| Off-topic questions refused | 9 of 10 |
| Plagiarism | 6% |

## 6. Viva questions and answers

### About the problem and the idea

**Q1. What problem does your project solve?**
People cannot easily tell which government schemes they qualify for because the rules are long and differ per scheme. Our app checks a profile against all schemes and explains each result.

**Q2. Who will use it?**
Citizens, CSC operators and block officers who screen many people, and scheme administrators who update rules.

**Q3. What is special about your project?**
Three things. The decision is made by code, not AI. Missing answers give "need more info" instead of "rejected". Every decision is stored with its own proof (copy of the rules, answers and a checksum).

**Q4. Why not just use ChatGPT or a chatbot?**
A chatbot can confidently give a wrong answer about someone's benefits, and that can cause real loss. Our eligibility answers come from tested code, and Q&A answers must come from stored text with sources.

### About MongoDB

**Q5. Why MongoDB and not MySQL?**
A scheme is one nested object with a rule tree that can go to any depth, and central and state schemes have different fields. MongoDB stores it as one document and reads it in one fetch. SQL would need many tables and joins, or a JSON column anyway.

**Q6. MongoDB has no foreign keys. How do you keep data correct?**
Unique indexes, JSON Schema validators in the database, Pydantic checks at the API, our own rule validator before publishing, and a rule that published versions and audit records are only inserted, never edited.

**Q7. What is a JSON Schema validator? Show an example.**
It is a rule attached to a collection so MongoDB rejects bad documents. For example, `evaluations` only accepts verdict ELIGIBLE, INELIGIBLE or NEEDS_MORE_INFO. I tried inserting "MAYBE" and it was rejected.

**Q8. What is a transaction and where did you use it?**
A transaction makes several writes succeed together or not at all. When we publish a new rule version, we insert the version, update the scheme to point to it, and mark the job published. If one fails, none are saved. It needs a replica set, so we run MongoDB as a one-node replica set.

**Q9. What indexes did you create and why?**
- Unique index on slug and email to stop duplicates.
- Compound index {status, level, state} to quickly pick published central schemes plus the user's state.
- {user_id, evaluated_at} to return a user's history already sorted.
- Text index for keyword search.
- TTL indexes to auto-delete old chat logs and counters.

**Q10. How do you know indexes actually help?**
We used `explain("executionStats")` and compared with a forced full scan using `hint({$natural: 1})`. For example, user history examined 5,906 documents without an index and 61 with it. All indexed plans show FETCH ← IXSCAN. (These numbers are in Chapter 7.4 of the report.)

**Q11. What is aggregation? Where did you use it?**
Aggregation is a pipeline of steps (`$match`, `$group`, `$sort` and so on) that processes data inside the database. We use it for the admin dashboard (verdict counts, most-missing answers, schemes per state) and for user history.

**Q12. What is a TTL index?**
It deletes documents automatically after a time. Chat logs are deleted after 30 days, and rate-limit counters after their time window ends.

**Q13. Explain your CRUD.**
Create: register user, save audit records. Read: list and search schemes, scheme detail. Update: save profile with upsert and consent, tracker status and checklist ($set with arrayFilters), grievance replies ($push). Delete: delete my profile and history, and retire a scheme (soft delete so history stays).

**Q14. What is "embedded snapshot" in your audit log?**
Each evaluation record contains a copy of the profile answers and the rules used at that time. So we can re-run it later without joins, and it stays correct even if the scheme or profile changes afterwards.

**Q15. What is the checksum for?**
A SHA-256 hash of the record's contents. If anyone edits the record later, the hash no longer matches. We tested this: after changing one stored value, the replay reported the checksum as invalid.

**Q16. Why is it a replica set when you run only one server?**
MongoDB transactions only work on replica sets. A one-node replica set gives us transactions without needing multiple machines.

**Q17. How would it scale to millions of users?**
The `evaluations` collection grows fastest, but it is insert-only, so it can be sharded on user_id or a hashed run_id, and old records archived. Scheme reads can go to replica-set secondaries.

### About the rules engine

**Q18. What is the rules engine?**
A small recursive function that walks a scheme's rule tree and checks it against the user's profile. Each rule gives PASS, FAIL or UNKNOWN. AND, OR and NOT combine them.

**Q19. What is three-valued logic and why use it?**
Besides true and false there is a third value, UNKNOWN, for answers the user did not give. Without it, a blank answer would wrongly become "not eligible". With it, the app says "tell us your land holding and we can check."

**Q20. What is the "next best question"?**
After a check, the engine counts which missing answer appears most across the "need more info" schemes and suggests that one first, because it settles the most schemes.

**Q21. How do rules get into the system?**
A script reads the Eligibility and Exclusions text and suggests rules with the exact sentence each came from. The validator checks them. Only hand-checked rules are published (16 schemes); the rest are used only as clearly labelled "unverified" recommendation hints.

**Q22. What if the extractor makes a wrong rule?**
The validator catches many errors (unknown questions, bad values, a quote that is not in the source, numbers that do not match, contradictions). Nothing is published without human approval. In fact, the validator caught a mistake in my own hand-written rules: I had typed an income limit of ₹2.5 lakh, but the source said ₹1.5 lakh.

**Q23. Is the extractor an AI model?**
No. It uses text patterns (regular expressions). A language model could replace it later behind the same validator and human review. We say this in the limitations.

**Q24. How do you handle a scheme changing its rules?**
We never edit the old rules. We publish a new version with the reviewer's name and a change note. Old checks still point to the version they used, so we can show what was true on that day.

### About search and Q&A

**Q25. How does the Ask page work?**
The question is classified. Eligibility questions go to the rules engine. Information questions use search: keyword search and meaning-based search are merged, the best 6 text pieces are used, and the answer is built with a citation for each sentence. Off-topic questions are refused.

**Q26. What is Reciprocal Rank Fusion?**
A way to merge two ranked lists. Each item's score is the sum of 1/(60 + rank) across the lists, so items near the top of both lists win.

**Q27. What are embeddings?**
A list of numbers (256 in our case) that represents the meaning of a piece of text, so similar texts have similar numbers. We compute them offline using TF-IDF and SVD, so no model download is needed.

**Q28. Does your project use AI?**
Only optionally. If an API key is set, a language model can rewrite the answer from the retrieved text. Without a key, the answer is built directly from the best sentences, and the app works fully offline. In both cases, the model never decides eligibility.

**Q29. How do you stop wrong answers?**
Answers can only use the retrieved text. The code checks that every citation points to a real source. If there is no valid citation, or the search results are weak, the answer is replaced with "I don't have reliable information on that. Please check myscheme.gov.in." Off-topic questions are refused.

**Q30. How well does the search work?**
We tested 200 questions where we knew the right scheme. When the question names the scheme, the right scheme is in the top 5 every time (1.00). When the question only describes the scheme, hybrid gets 0.68 and similarity-only gets 0.82. So combining is not always better; we report this honestly and plan to weight the two lists differently.

### Security, testing and honesty

**Q31. How is security handled?**
Passwords are hashed with PBKDF2-SHA256 and a random salt, and login gives a JWT that expires in 12 hours. Users and admins have different roles, and admin pages return HTTP 403 for others. We never store Aadhaar. Profiles are saved only with consent, and users can delete their data. The chat endpoint is rate-limited.

**Q32. How did you test it?**
114 automated tests: truth tables for AND/OR/NOT, random property tests with Hypothesis (for example NOT(NOT(x)) equals x), 35 sample profiles with expected verdicts, validator tests, and end-to-end API tests on a separate test database. All pass.

**Q33. What are the limitations?**
The data is a 2024 snapshot and may be outdated, so the app shows when each scheme was last verified. Only 16 schemes have hand-checked published rules, and the other schemes only have machine-read rules, which are shown as "unverified" hints. Embeddings handle English best. We use a local MongoDB; the Atlas `$vectorSearch` code path is written but we tested the local fallback.

**Q34. What would you do next?**
Move to MongoDB Atlas, use an official data feed, add a Hindi interface and a multilingual embedding model, and tune the hybrid search weights.

**Q35. Which parts did you build yourselves?**
*(Answer honestly with your own contribution.)* The project covers data parsing, the MongoDB design, the rules engine, the web app, the search and the tests. Be ready to open any file and explain it.

### Grievance Portal and the Ask fixes (new)

**Q36. What is the Grievance Portal?**
A logged-in user can file a complaint about a scheme, for example an application delay or a benefit not received, and can link it to one of their past eligibility checks. They get a ticket number like GRV-2026-000001 and follow every reply in a timeline. They can reopen a complaint if it isn't solved. Admins see a queue, change the status and priority, and reply.

**Q37. How do you make sure two complaints never get the same ticket number?**
A `counters` collection holds the last number used. We call `find_one_and_update` with `$inc` and `upsert`. MongoDB does the increment as one atomic step, so even two requests at the same moment get different numbers. A test files two complaints and checks the numbers follow on.

**Q38. Why is the timeline stored inside the grievance document?**
A complaint and its history are always read together, so we embed the history as an array and add each reply with `$push`. One fetch returns everything. The status change and the new timeline entry are written in one update, so they always agree.

**Q39. Where did you use `$lookup` and `$facet`?**
`$lookup` in the admin queue joins each complaint with the filer's email from `users`, so user details are not copied into every complaint. `$facet` in the dashboard returns, in one query, complaints by status, complaints by category, and the average hours to resolve.

**Q40. Who can see a grievance?**
Only the user who filed it, and admins. Anyone else gets HTTP 403. Filing needs login, a linked check must be from the user's own history, and a validator in MongoDB only accepts our categories, statuses and ticket format.

**Q41. The Ask page gave wrong answers earlier. What did you fix?**
Three things:
1. Relevance is now checked per passage. Each passage must contain the question's topic words, so "car loan" no longer returns education-loan text.
2. A spelling map and plural matching (yojna → yojana, aadhar → aadhaar, fishermen → fisherman) stop real questions being refused as off-topic.
3. The sentence splitter no longer cuts "Rs 10.00 lakh" in half.

Short topics like "atal yojna" now list the matching schemes. When nothing matches, the app says so and suggests related schemes.

## 7. Questions where students usually get stuck (practice these)

- "Show me a document in MongoDB Compass." → open `scheme_assistant` → `schemes` → `apy`, and show `eligibility`.
- "Show me an audit record." → `evaluations` → one document → point to `profile_snapshot`, `rules_snapshot`, `checksum`.
- "Show a validator rejecting data." → try inserting `{verdict: "MAYBE"}` in `evaluations`.
- "Show an index being used." → `explain("executionStats")` and point to `IXSCAN`.
- "Why is this scheme eligible?" → open the result and read the reasons line by line.

## 8. Demo order (5 minutes)

1. Check page: age 29, Assam, income 90,000, BPL yes, weaver → show the three groups and reasons.
2. Answer the "next best question" and watch the verdicts change.
3. Ask: "Am I eligible for Atal Pension Yojana?" then "What documents are needed for Aam Aadmi Bima Yojana?" then an off-topic question.
4. Scheme page: rule tree, source quotes, version history.
5. Grievances: file one as a user, then log in as admin and resolve it; show the timeline.
6. Admin login (/login → Admin tab): overview stats, coverage-gap map, grievance queue.
7. Compass: validator, indexes, `explain()`.
8. Run `pytest -q`.

**Start commands** (if the app is not running):
```
powershell -ExecutionPolicy Bypass -File scripts\start_mongo.ps1
python -m uvicorn api.main:app --port 8000
```
Admin password is in `.env.demo`.
