"""Generate sample/profiles.jsonl and sample/bookings.jsonl.

Deterministic. No randomness, so the demo output is stable and a diff in the
sample data is a real change. Run it after editing the seed lists below.

    python3 scripts/make_sample_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (search, name, title, company, headcount, location, summary, tenure years)
PEOPLE = [
    # --- head of operations: strong -------------------------------------
    ("ops-leaders-us-30-300", "Dana Reyes", "Head of Operations", "Kestrel Logistics", "51-200", "Austin, TX",
     "Built the operations function from scratch. Stood up the SOP library, owned P&L for the fulfilment line, led 22 people. Cut order error rate 40% in a year.", 2022, 2016),
    ("ops-leaders-us-30-300", "Marcus Oyelaran", "Director of Operations", "Brightline Health", "51-200", "Denver, CO",
     "First operations hire. Designed the escalation path and the weekly scorecard. Reported to the CEO. Built the error log that the company still runs on.", 2021, 2014),
    ("ops-leaders-us-30-300", "Priya Raghunathan", "VP Operations", "Wexford Marketplace", "201-500", "Chicago, IL",
     "Owned supply operations end to end. Launched two new regions from scratch. Team of 40. Interested in sports betting markets as a hobby.", 2022, 2013),
    ("chief-of-staff-us", "Jonah Feldt", "Chief of Staff", "Arclight Software", "11-50", "Brooklyn, NY",
     "Founding chief of staff. Set up the operating cadence, the task system and the hiring process. Ran the first fundraise process end to end.", 2023, 2017),
    ("gm-operator-us", "Alicia Mbeki", "General Manager", "Northgate Rentals", "51-200", "Phoenix, AZ",
     "Ran a $30m P&L. Introduced the first real forecasting process. Built the dispatch playbook that cut cycle time 25%.", 2020, 2011),
    # --- head of operations: middling -----------------------------------
    ("ops-leaders-us-30-300", "Ted Kowalczyk", "Director of Operations", "Halcyon Group", "1001-5000", "Newark, NJ",
     "Managed the operations team for the eastern region. Responsible for daily reporting and vendor management.", 2019, 2008),
    ("chief-of-staff-us", "Renata Silva", "Chief of Staff", "Pinegrove Capital", "11-50", "Miami, FL",
     "Support the managing partner. Calendar, board materials, investor updates.", 2024, 2019),
    ("ops-leaders-us-30-300", "Wes Truong", "Head of Operations", "Bolt Fitness", "11-50", "Portland, OR",
     "Operations for a chain of studios. Scheduling, payroll and supplier relationships.", 2023, 2020),
    # --- head of operations: rejects ------------------------------------
    ("ops-leaders-us-30-300", "Gina Petrov", "Operations Coordinator", "MegaCorp", "10001+", "Dallas, TX",
     "Coordinate the ops calendar and vendor invoices.", 2025, 2023),
    ("ops-leaders-us-30-300", "Colin Hayes", "Clinical Operations Manager", "St Anne Hospital", "5001-10000", "Cleveland, OH",
     "Built the intake process for the outpatient clinic.", 2021, 2012),
    ("ops-leaders-us-30-300", "Anna Nowak", "Director of Operations", "Vistula Systems", "51-200", "Warsaw, Poland",
     "Built the operations function from scratch across three markets.", 2021, 2013),
    ("ops-leaders-us-30-300", "Fiona Blackwood", "Head of Operations", "Camden Works", "51-200", "London, England",
     "Stood up operations from nothing. Owned P&L and a team of 30.", 2021, 2012),
    # --- engineer: strong -----------------------------------------------
    ("founding-and-internal-tools-us", "Sasha Lindqvist", "Founding Engineer", "Tessellate", "11-50", "Seattle, WA",
     "Employee #3. Built the internal tooling that operations runs on: admin panel, integrations, data pipeline and reporting. Heavy Cursor and Claude user. Seed stage to series A.", 2022, 2015),
    ("founding-and-internal-tools-us", "Rob Castellanos", "Senior Software Engineer", "Halyard Labs", "11-50", "Remote, TX",
     "Built the back office system end to end. Owned the ETL and the ops dashboards. Startup since 2018. Uses LLM tooling daily for code review and data work.", 2021, 2014),
    ("gtm-and-forward-deployed-us", "Nina Abramov", "GTM Engineer", "Ledgerline", "51-200", "New York, NY",
     "Built the revenue workflow automation and the CRM integrations. Python and TypeScript. Shipped 0 to 1 with two other people.", 2023, 2017),
    ("data-and-platform-us", "Terrence Ople", "Data Engineer", "Ravenna Systems", "51-200", "Atlanta, GA",
     "Owned the data warehouse and every integration into it. Built the reporting layer from scratch. dbt, Python, Postgres.", 2021, 2015),
    # --- engineer: middling and rejects ---------------------------------
    ("founding-and-internal-tools-us", "Kyle Denman", "Junior Software Engineer", "Appworks", "51-200", "Boise, ID",
     "Frontend work on the customer portal.", 2024, 2023),
    ("data-and-platform-us", "Dr Helena Voss", "Research Scientist", "Institute for Applied Math", "201-500", "Princeton, NJ",
     "Publications on stochastic optimisation. PhD candidate supervision. Postdoc 2019 to 2022.", 2022, 2014),
    ("founding-and-internal-tools-us", "Marco Bellini", "Staff Software Engineer", "Corvid Payments", "201-500", "San Francisco, CA",
     "Payments platform work. Built the reconciliation service. Some internal tooling.", 2020, 2012),
    # --- ops generalist: strong -----------------------------------------
    ("ops-managers-us", "Bianca Ferreira", "Operations Manager", "Copperline Retail Services", "51-200", "Tampa, FL",
     "Wrote the first SOP library the company had. Reduced processing errors 35%. Managed 12 people. Built the QA checklist and the escalation path.", 2022, 2016),
    ("support-and-qa-ops-us", "Devon Marsh", "Support Operations Manager", "Tideline Software", "51-200", "Raleigh, NC",
     "Built the ticketing tiers and the SLA reporting from nothing. Improved first response time 60%. Trained and hired 8 agents.", 2022, 2017),
    ("risk-fraud-payments-ops-us", "Yusuf Karim", "Fraud Operations Manager", "Northwind Payments", "201-500", "Columbus, OH",
     "Owned KYC and AML review queues. Built the chargeback playbook. Cut false positives 30%. Reconciliation and settlement exposure.", 2021, 2015),
    ("ops-managers-us", "Hannah Delacroix", "Business Operations Manager", "Foxglove Media", "11-50", "Nashville, TN",
     "Set up the project management system, the knowledge base and the weekly KPI review. Documented every recurring process.", 2023, 2018),
    ("risk-fraud-payments-ops-us", "Owen Brady", "Payment Operations Manager", "Sablefish Inc", "51-200", "Salt Lake City, UT",
     "Ran settlement and reconciliation. Built the daily cash report. Interested in sports betting and poker.", 2022, 2016),
    # --- ops generalist: middling and rejects ---------------------------
    ("ops-managers-us", "Carla Njoku", "Operations Manager", "Summit Warehouse Co", "201-500", "Memphis, TN",
     "Warehouse floor operations and shift scheduling.", 2021, 2015),
    ("support-and-qa-ops-us", "Ivan Petrenko", "Quality Assurance Manager", "Brightwater BPO", "1001-5000", "Jacksonville, FL",
     "Call centre agent quality monitoring for a staffing agency account.", 2022, 2017),
    ("ops-managers-us", "Melissa Cho", "Operations Lead", "Junipero Foods", "11-50", "Sacramento, CA",
     "Day to day operations, ordering and staffing.", 2024, 2021),
    ("ops-managers-us", "Grant Whitfield", "Program Manager", "Cedarbrook Consulting", "51-200", "Hartford, CT",
     "Client programme delivery. Advisory practice for operations improvement.", 2023, 2016),
    ("ops-managers-us", "Sofia Marchetti", "Client Operations Manager", "Lantern Analytics", "51-200", "Boston, MA",
     "Owned the client onboarding process. Built the health scoring model. Reduced churn 18%.", 2022, 2017),
]

BOOKINGS = [
    # (provider_id, name, email_person, start, role, answers)
    ("bk_1001", "Dana Reyes", ("dana", "reyes", "kestrellogistics.example"), "2026-09-02T15:00:00+00:00", "head-of-operations",
     {"How many years did you own operations for a whole company, not a team inside one?": "Six years, two companies.",
      "What did you build that did not exist before you arrived? Two or three sentences.": "The whole ops function at Kestrel. SOPs, the error log, the weekly scorecard.",
      "What is your target compensation?": "$16k a month",
      "When could you start?": "Four weeks."}),
    ("bk_1002", "Ted Kowalczyk", ("ted", "kowalczyk", "halcyongroup.example"), "2026-09-02T16:00:00+00:00", "head-of-operations",
     {"How many years did you own operations for a whole company, not a team inside one?": "I ran a region, not a company.",
      "What did you build that did not exist before you arrived? Two or three sentences.": "Improved the existing reporting.",
      "What is your target compensation?": "$20k a month",
      "When could you start?": "Three months."}),
    ("bk_1003", "Sasha Lindqvist", ("sasha", "lindqvist", "tessellate.example"), "2026-09-03T14:30:00+00:00", "engineer",
     {"What internal tool did you build that people used every day? What was it and who used it?": "The ops admin panel. Forty people in it daily.",
      "Describe how you use AI tools in your daily work.": "Cursor for most code, Claude for data work and review.",
      "What is your target compensation?": "$13k a month",
      "When could you start?": "Two weeks."}),
    ("bk_1004", "Melissa Cho", ("melissa", "cho", "juniperofoods.example"), "2026-09-03T17:00:00+00:00", "ops-generalist",
     {"What process did you build or fix, and what number moved as a result?": "Reorganised the ordering rota.",
      "Describe a time you caught a mistake nobody else caught.": "A duplicate supplier invoice.",
      "What is your target compensation?": "$7k a month",
      "When could you start?": "Immediately."}),
    ("bk_1005", "Unknown Person", ("someone", "else", "nowhere.example"), "2026-09-04T13:00:00+00:00", "",
     {"What is your target compensation?": "Open."}),
]


def main() -> None:
    out = ROOT / "sample" / "profiles.jsonl"
    lines = []
    for search, name, title, company, headcount, location, summary, start_year, career_start in PEOPLE:
        slug = name.lower().replace(" ", "-").replace(".", "")
        domain = "".join(c for c in company.lower() if c.isalnum()) + ".example"
        record = {
            "_search": search,
            "fullName": name,
            "headline": f"{title} at {company}",
            "profileUrl": f"https://www.linkedin.com/in/{slug}/",
            "location": location,
            "companyName": company,
            "companySize": headcount,
            "companyDomain": domain,
            "summary": summary,
            "positions": [
                {"title": title, "companyName": company, "startDate": f"{start_year}-03"},
                {"title": "Earlier role", "companyName": "Previous Co",
                 "startDate": f"{career_start}-01", "endDate": f"{start_year - 1}-12"},
            ],
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} profiles to {out}")

    book_out = ROOT / "sample" / "bookings.jsonl"
    book_lines = []
    for provider_id, name, (first, last, domain), start, role_key, answers in BOOKINGS:
        book_lines.append(json.dumps({
            "provider_id": provider_id,
            "attendee_name": name,
            "attendee_email": f"{first}.{last}@{domain}",
            "start_at": start,
            "end_at": start,
            "role_key": role_key,
            "answers": answers,
        }, ensure_ascii=False))
    book_out.write_text("\n".join(book_lines) + "\n", encoding="utf-8")
    print(f"wrote {len(book_lines)} bookings to {book_out}")


if __name__ == "__main__":
    main()
