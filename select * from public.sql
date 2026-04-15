select * from public.group_member_stats;

DELETE FROM public.group_member_stats
WHERE group_id IN (1070187533, 822841333);

-- Insert data into 'public.group_member_stats'
INSERT INTsO public.group_member_stats (group_id, group_name, member_count, stat_time,stat_time )
VALUES (value1, value2);

INSERT INTO group_member_stats (group_id, group_name, member_count, stat_date, stat_time, created_at, updated_at)
VALUES
    (822841333, '', 550, '2026-04-13', '2026-04-13 12:00:00+08:00', '2026-04-13 12:00:00+08:00', '2026-04-13 12:00:00+08:00'),
    (822841333, '', 583, '2026-04-14', '2026-04-14 12:00:00+08:00', '2026-04-14 12:00:00+08:00', '2026-04-14 12:00:00+08:00')
ON CONFLICT (group_id, stat_date) DO UPDATE SET
    member_count = EXCLUDED.member_count,
    stat_time = EXCLUDED.stat_time,
    updated_at = EXCLUDED.updated_at;

INSERT INTO group_member_stats (group_id, group_name, member_count, stat_date, stat_time, created_at, updated_at)
VALUES
    (1070187533, '', 550, '2026-04-13', '2026-04-13 12:00:00+08:00', '2026-04-13 12:00:00+08:00', '2026-04-13 12:00:00+08:00'),
    (1070187533, '', 583, '2026-04-14', '2026-04-14 12:00:00+08:00', '2026-04-14 12:00:00+08:00', '2026-04-14 12:00:00+08:00')
ON CONFLICT (group_id, stat_date) DO UPDATE SET
    member_count = EXCLUDED.member_count,
    stat_time = EXCLUDED.stat_time,
    updated_at = EXCLUDED.updated_at;