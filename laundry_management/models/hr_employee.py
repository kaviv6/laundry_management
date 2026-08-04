# Removed: is_rider boolean field on hr.employee.
# Rider identity is now determined solely by membership in group_laundry_manager.group_laundry_rider.
# The rider_id / laundry_person_id domain filters on laundry.order and laundry.pickup.request
# use groups_id to filter users in that group — no hr dependency needed.
