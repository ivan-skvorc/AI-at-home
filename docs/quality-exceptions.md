# Quality exceptions

Redundancies kept on purpose. [change_cycle.md](../change_cycle.md) level 3
logs every quality finding it does not fix here, and checks each entry's
"Fix when" condition on every run: once the condition is met, the redundancy
is fixed and the entry deleted. Entries whose condition still holds are not
reported again.

Format (one entry per redundancy):

```markdown
### <what is duplicated, in a few words>
Where: <the files>
What: <the redundancy>
Why kept: <a cost estimate, a technical constraint, an external dependency, or "needs owner decision">
Fix when: <a condition anyone can check>
Added: <YYYY-MM-DD>, <PR link>
```

No entries yet.
