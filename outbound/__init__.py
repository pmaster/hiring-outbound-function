"""Outbound recruiting pipeline.

Find candidate profiles, score them against a role ICP, enrich to a work
email, send a short sequence with the job description and a screener link,
then read the bookings back and cancel the ones that are not a fit.

Standard library only. Python 3.11 or later.
"""

__version__ = "0.1.0"
