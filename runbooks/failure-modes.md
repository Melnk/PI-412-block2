# Observable failure modes

Classify the observable failure mode, not the ultimate reason why it happened.
Use this same taxonomy for all incidents, without looking at expected test answers.

- database: connections in use equal the pool limit AND application logs report connection-acquisition timeouts. The unknown reason for connections being held does not invalidate the observed exhausted pool.
- release: a version change precedes failures AND logs or metrics tie the failures to the new version. A recent release alone is not enough.
- application: application exception details identify failing code, while no stronger exhausted-pool or release-specific explanation is supported.
- unknown: none of these observable modes has consistent supporting evidence from at least two source types, or evidence conflicts.

Do not confuse a connection-acquisition timeout with a generic application exception.
Source diversity is a useful check, not proof that data are true or statistically independent.
