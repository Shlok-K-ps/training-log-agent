"""The training-day agent: one durable case per athlete per scheduled training day.

`engine` owns the loop, `policy` holds the fixed rules, `store` is its memory,
`transport` is how it reaches athletes and the coach, and `adaptation` is the
one bounded way its behaviour changes with experience.
"""
