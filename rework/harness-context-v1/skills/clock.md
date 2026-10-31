# Clock and timezone

Status: STAGED DESIGN — not loaded or active. Version 1, 2026-10-25.

Read the host clock through the registered clock tool for current date/time. Do not answer from model training or a stale conversation timestamp. Use the user's explicitly configured IANA timezone when available. Otherwise label the returned host timezone and do not imply it is the user's location.

Record observed UTC time, converted local time, offset and named zone. Test daylight-saving boundaries and invalid timezone handling. “EST” may mean a fixed offset or colloquial Eastern time; clarify when that distinction affects a schedule. A clock read does not prove synchronization with an external time authority.

Clock and web are independent tools. An offline search provider must not prevent a local date answer; a working clock does not prove internet access. Do not schedule a job merely because a user asks the time.
