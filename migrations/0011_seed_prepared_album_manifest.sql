-- Import the versioned prepared-album manifest into the operational D1 catalog.
-- The cron planner turns these rows into release enrichment jobs. INSERT OR
-- IGNORE keeps a migration retry idempotent and never resets a target that has
-- already been planned, collected, or ignored.

INSERT OR IGNORE INTO prepared_album_targets
    (release_mbid, artist, title, genre, priority, status)
VALUES
    ('e32a3f0b-1c19-3170-bb1c-650893774744', 'Miles Davis', 'Kind of Blue', 'jazz', 100, 'pending'),
    ('b7cf6ab3-1fab-45cd-97a2-8e684ffcada1', 'Miles Davis', 'Bitches Brew', 'jazz', 95, 'pending'),
    ('b087b874-1a0b-4df6-99e1-4beb58ebecf3', 'BLACKPINK', 'BORN PINK', 'kpop', 90, 'pending'),
    ('f4427ccd-140f-4bfa-8f3f-9ad24222e77a', 'BTS', 'Dynamite', 'kpop', 85, 'pending'),
    ('6aff8f36-d807-4e22-aafe-f65859ce1d71', 'Milton Nascimento & Lô Borges', 'Clube da Esquina', 'mpb', 100, 'pending'),
    ('2b7fa52f-2123-4d14-b84e-f8a8b23e4cbd', 'Novos Baianos', 'Acabou Chorare', 'samba-rock', 100, 'pending'),
    ('34f5ca0c-8112-4625-9142-169412566b7a', 'Elis Regina & Tom Jobim', 'Elis & Tom', 'mpb', 95, 'pending'),
    ('2408c96c-a716-412b-9337-7efc485d1895', 'Stan Getz / João Gilberto featuring Antônio Carlos Jobim', 'Getz / Gilberto', 'bossa-nova', 95, 'pending'),
    ('4e03b3a5-8e95-4e7e-ba35-05eb0af25c83', 'Buena Vista Social Club', 'Buena Vista Social Club', 'son-cubano', 90, 'pending'),
    ('5cdb03e2-1abf-4030-b18e-1824a31a25c0', 'Stevie Wonder', 'Innervisions', 'soul', 90, 'pending'),
    ('a712cf75-1e80-4ea6-84d9-8eb8798a0edd', 'Joni Mitchell', 'Blue', 'folk', 90, 'pending'),
    ('322ec2d8-0179-4194-b052-90c5817dd4ed', 'The Dave Brubeck Quartet', 'Time Out', 'jazz', 85, 'pending'),
    ('38057097-d52d-4494-a92d-dd1582f9cc8a', 'The Strokes', 'The New Abnormal', 'indie-rock', 85, 'pending');
