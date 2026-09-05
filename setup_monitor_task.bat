@echo off
schtasks /create /tn "AdvisorAgentMonitor" /tr "\"D:\conda\envs\advisor\pythonw.exe\" \"D:\AI\advisor_agent\tools\monitor_daily.py\"" /sc DAILY /st 09:00 /f
schtasks /query /tn "AdvisorAgentMonitor"
