"""Shared ADK session.state key names, so agents and the orchestrator agree
on the contract without importing each other's internals."""

PATIENT_RESULT = "patient_result"
PLAN = "plan"
ROUTING_RESULT = "routing_result"
APPOINTMENT_RESULT = "appointment_result"
DOCUMENT_RESULT = "document_result"
FOLLOWUP_RESULT = "followup_result"
SAFETY_VERDICT_PRE = "safety_verdict_pre"
SAFETY_VERDICT_POST = "safety_verdict_post"
