import sys, pathlib, zipfile, xml.etree.ElementTree as ET
sys.path.insert(0, 'src')
p = pathlib.Path('AC_DC-Highway To Hell-12-22-2025.gp')
with zipfile.ZipFile(p) as zf:
    with zf.open('Content/score.gpif') as f:
        root = ET.fromstring(f.read())

master_bars = root.findall('.//MasterBar')
track_index = 3  # Malcolm Young
for i in [58, 59, 60, 61, 62]:
    mb = master_bars[i]
    bars_text = (mb.findtext('Bars') or '').split()
    if len(bars_text) > track_index:
        bar_id = bars_text[track_index]
        bar = root.find(f'Bars/Bar[@id="{bar_id}"]')
        if bar is not None:
            voices_text = bar.findtext('Voices') or ''
            print(f'--- Bar {bar_id} (MasterBar {i+1}, display ~{i}): voices={voices_text}')
            for vid in voices_text.split():
                voice = root.find(f'Voices/Voice[@id="{vid}"]')
                if voice is not None:
                    beats_text = (voice.findtext('Beats') or '').split()
                    print(f'  Voice {vid}: {len(beats_text)} beats')
                    for beat_id in beats_text:
                        beat = root.find(f'Beats/Beat[@id="{beat_id}"]')
                        if beat is not None:
                            notes_text = beat.findtext('Notes') or ''
                            rest_el = beat.find('Rest')
                            dynamic_el = beat.find('Dynamic')
                            print(f'    Beat {beat_id}: notes=[{notes_text}] rest={rest_el is not None}')
                            for note_id in notes_text.split()[:4]:
                                note = root.find(f'Notes/Note[@id="{note_id}"]')
                                if note is not None:
                                    tie_el = note.find('Tie')
                                    tie = tie_el is not None
                                    print(f'      Note {note_id}: tie={tie} tie_attribs={tie_el.attrib if tie_el is not None else None}')
