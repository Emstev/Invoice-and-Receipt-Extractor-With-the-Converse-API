# 🧾 Ledgerline: Invoice and Receipt Extractor with the Amazon Bedrock Converse API

> A folder of invoices and receipts goes in. **Checked data** and **one spreadsheet** come out. Anything the tool is not sure about goes to a person, **never straight into the accounts**.

![AWS](https://img.shields.io/badge/AWS-Bedrock%20Converse%20API-FF9900?logo=amazonaws&logoColor=white)
![Python](https://img.shields.io/badge/Python-CloudShell-3776AB?logo=python&logoColor=white)
![Models](https://img.shields.io/badge/Models-Nova%20Lite%20%7C%20Nova%20Pro-blueviolet)
![Built with](https://img.shields.io/badge/Built%20with-Cloudboosta-purple)

![Architecture](architecture)

---

## 📌 The problem

Ledgerline is a small bookkeeping firm in the UK. Every month clients send a pile of supplier invoices and till receipts, as PDFs and phone photos. Two people type each one into the accounts: the supplier, the dates, the VAT and every line. It is slow, and typing mistakes slip through.

## 💡 The solution

A batch tool, plus a simple web page, that:

1. Sends each document to **Amazon Bedrock** through the **Converse API**
2. Gets the model to answer in **JSON that follows a schema**
3. **Checks the answer in code**: totals, VAT and dates
4. Sends a failed document **back to the model once**, with the errors
5. Marks anything still wrong as **`needs_review`** (Send to a person)
6. Logs every step, works out the **cost of each document**, and writes **one CSV**

> 💡 **Key idea:** the model reads the page, but **your code decides what is trusted**. A model that sounds confident can still be wrong, so the arithmetic is checked by Python.

---

## 🧰 Tech stack

| Layer | Service or tool | Purpose |
|---|---|---|
| Model access | Amazon Bedrock Converse API | One API for reading documents with different models |
| Models | Amazon Nova Lite, Amazon Nova Pro | Compared on the same 10 documents |
| Script | Python in AWS CloudShell | `make_samples.py`, `extract.py`, `compare.py` |
| Test data | reportlab, pillow | 6 PDF invoices and 4 receipt pictures |
| Web page | S3 (private) + CloudFront | HTTPS front end |
| API | API Gateway HTTP API + Lambda | Runs `extract.py` for each upload |

---

## 🛡️ Built-in reliability

| Feature | What it does |
|---|---|
| JSON schema output | The model must answer in a fixed structure |
| Forced tool | Nova Lite can be forced to answer through a tool. If the tool call fails, the tool logs "switching to text mode" and carries on |
| Validation | `validate()` checks subtotal, VAT (from the line rates), total and dates |
| One repeat | A failed document is sent back to the model once with the errors |
| Backoff and retry | Waits and retries when Bedrock is busy |
| Logging | Every step is logged |
| Cost tracking | Cost per document from input and output tokens |
| Human in the loop | Still failing after the repeat → `needs_review` |

---

## 🚀 Step-by-step setup

> **Prerequisites:** an AWS account, Amazon Bedrock model access for **Nova Lite** and **Nova Pro**, and AWS CloudShell in the region you use for the lab.

### Step 1: Install the PDF and picture libraries (private folder)

In plain English: these two libraries only draw the made-up test documents, so we install them in a private folder instead of system-wide.

```bash
mkdir -p ~/ledgerline && cd ~/ledgerline
pip install --target ./libs reportlab pillow
export PYTHONPATH="$PWD/libs:$PYTHONPATH"
```

> ✅ **Checkpoint:** `python3 -c "import reportlab, PIL; print('ok')"` prints `ok`.

### Step 2: Make the 10 test documents

`make_samples.py` is **test-data code only**. It never calls AWS.

| Part | What it does |
|---|---|
| `DOCS` | Lists the 10 made-up documents: supplier, dates, lines, VAT and any mistake printed on purpose |
| `figures()` | Works out subtotal, VAT and total to the penny |
| `make_pdf()` | Draws the 6 invoices as PDFs with reportlab |
| `make_receipt()` | Draws the 4 till receipts as PNG and JPG with pillow (two tilted and blurred like phone photos) |
| `main()` | Writes everything into `samples/` and the correct answers into `ground_truth.json` |

```bash
python3 make_samples.py
ls samples/
```

> ✅ **Checkpoint:** `samples/` holds 6 PDFs and 4 pictures, and `ground_truth.json` exists.

### Step 3: Extract one invoice with Nova Lite

Add `extract.py`, then run it on a single invoice first.

> ✅ **Checkpoint:** you get JSON with the supplier, dates, lines, VAT and total, plus a log line with tokens and cost.

### Step 4: Run all 10 documents

Run `extract.py` over the whole `samples/` folder, then open the CSV and the log.

| Document | Expected result |
|---|---|
| `01_harbour_lane_invoice.pdf` | ✅ Passes. Total £162.60 |
| `05_northgate_it_invoice.pdf` | ⚠️ `needs_review`. Wrong VAT printed on purpose: VAT from the line rates is **82.90** but `vat_total` is **72.90** |

> 💡 **Why invoice 05 fails on purpose:** on try 2 the model often changes the VAT to 82.90, and then the totals no longer add up. The VAT check rejects both tries, so a person reviews it. That is the system working, not a bug.

### Step 5: Compare Nova Lite and Nova Pro

Run the same 10 documents through **Nova Pro**, and through **Nova Lite with a forced tool**, then score all three runs against `ground_truth.json`.

```bash
python3 compare.py
```

`compare.py` prints the numbers your recommendation needs: accuracy, cost and the misses for each model, plus the script's pick.

> 📌 Nova Pro costs about **13 times more per token** than Nova Lite, so it has to earn that price in accuracy.

Recommendation: nova-lite-text. It is the cheapest model with at least 95% field accuracy and every document status as expected, so Nova Pro's roughly 13x higher price per token is not justified for this task.
⚠️ One honest caveat: this was 10 documents, so say "on my test set" in the post, or add a line in the README's next steps about growing the test set.


### Step 6: Deploy the Ledgerline Invoice Reader page

| Component | Config |
|---|---|
| S3 | Private bucket holding the page |
| CloudFront | HTTPS in front of the bucket |
| API Gateway | HTTP API, file sent as **base64 text under 4 MB** |
| Lambda | Runs `extract.py` |
| Page | Table of fields, failed checks highlighted, **Send to a person** label, **Download as CSV** |

> ✅ **Checkpoint 1:** drop in `01_harbour_lane_invoice.pdf` and click **Read document**. You see a green **All checks passed** banner, supplier **Harbour Lane Stationery Ltd**, total **£162.60**, five green checks, invoice number HLS-10432, subtotal £135.50 and VAT £27.10.
>
> ✅ **Checkpoint 2:** drop in `05_northgate_it_invoice.pdf`. You see a yellow **Send to a person** banner, the **VAT matches** check flagged, and the VAT row highlighted.

### Step 7: Clean up

Delete the CloudFront distribution, API, Lambda and S3 bucket when you finish, so you do not pay for idle resources.

---

## 📊 Results

Fill these in from your `compare.py` output.

| Run | Accuracy vs answer key | Cost for 10 documents | Misses |
|---|---|---|---|
| Nova Lite | _/10 | $_ | _ |
| Nova Lite + forced tool | _/10 | $_ | _ |
| Nova Pro | _/10 | $_ | _ |

**Recommendation:** _write one sentence here: which model, and why._

---

## 🗂️ Suggested repo structure

```
ledgerline-invoice-extractor/
├── README.md
├── architecture.svg
├── make_samples.py
├── extract.py
├── compare.py
├── ground_truth.json
├── samples/              # the 10 made-up documents
├── web/index.html        # Ledgerline Invoice Reader page
├── lambda/               # Lambda handler
├── results/              # CSV and log
└── docs/screenshots/
```

## 🔮 Next steps

- Add a confidence flag per field, not just per document
- Store results in DynamoDB and notify a reviewer when a document needs review
- Try more document types (credit notes, statements)
- Grow the test set well beyond 10 documents

---

## 🎓 About

Built as part of the **Cloudboosta Academy** AI on AWS course.
**Emmanuel Ekwonu**: Cloud / DevOps / SRE engineer.

`#LearningWithCloudboosta` `#AmazonBedrock` `#AWS` `#GenerativeAI`
