# Full mission snapshot; latched (transient_local) so late joiners catch up.
# Re-published whenever tasks are injected. Agents add unknown ids only.
float64 stamp
auction_msgs/TaskSpec[] tasks
