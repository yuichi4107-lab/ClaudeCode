#!/usr/bin/env python3
"""
Convert Japanese history video script to CSV format.

This script converts a script file (Markdown format with dialogue) to CSV format
suitable for video production, with automatic handling of:
- Sentence splitting by punctuation (。！？)
- Line length limiting (30 characters per line for long sentences)
- Pause insertion between speaker changes
- Speaker-to-VoiceID mapping

Usage:
    python3 convert_to_csv.py <input_script.md> <output_script.csv>
"""

import csv
import re
import sys


def convert_script_to_csv(input_file, output_file):
    """
    Convert script file to CSV format.
    
    Args:
        input_file: Path to input script file (Markdown format)
        output_file: Path to output CSV file
    """
    # Read input file
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split into lines
    lines = content.split('\n')
    
    # CSV data storage
    csv_data = []
    row_number = 1
    
    # Speaker to VoiceID mapping
    speaker_map = {
        'ミユ': 'Female_3',
        'ヨウイチ': 'Male_15'
    }
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines and markdown headers
        if not line or line.startswith('#'):
            continue
        
        # Handle pause lines
        if line.startswith('pause,,,'):
            csv_data.append([str(row_number), 'pause', '', '', 'PAUSE_0.5S', 1])
            row_number += 1
            continue
        
        # Handle dialogue lines
        match = re.match(r'^(ミユ|ヨウイチ)「(.+)」$', line)
        if match:
            speaker = match.group(1)
            dialogue = match.group(2)
            voice_id = speaker_map.get(speaker, '')
            
            # Split dialogue by punctuation (。！？)
            sentences = re.split(r'([。！？])', dialogue)
            
            # Recombine split sentences
            combined_sentences = []
            temp = ''
            for i, part in enumerate(sentences):
                temp += part
                if part in ['。', '！', '？']:
                    combined_sentences.append(temp)
                    temp = ''
            if temp:  # Add remaining text
                combined_sentences.append(temp)
            
            # Process each sentence
            for sentence in combined_sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                # If longer than 30 characters, split by comma to keep under 30 characters
                if len(sentence) > 30:
                    # Split by comma
                    parts = sentence.split('、')
                    current_line = ''
                    
                    for i, part in enumerate(parts):
                        # Add comma back (except for last part)
                        if i < len(parts) - 1:
                            part_with_comma = part + '、'
                        else:
                            part_with_comma = part
                        
                        # Check if can add to current line
                        if len(current_line + part_with_comma) <= 30:
                            current_line += part_with_comma
                        else:
                            # Output current line
                            if current_line:
                                csv_data.append([str(row_number), 'dialogue', current_line, speaker, voice_id, 1])
                                row_number += 1
                            current_line = part_with_comma
                    
                    # Output remaining
                    if current_line:
                        csv_data.append([str(row_number), 'dialogue', current_line, speaker, voice_id, 1])
                        row_number += 1
                else:
                    # Output as-is if 30 characters or less
                    csv_data.append([str(row_number), 'dialogue', sentence, speaker, voice_id, 1])
                    row_number += 1
    
    # Write to CSV file
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        # Header row
        writer.writerow(['No', 'Type', 'Content', 'Speaker', 'VoiceID', 'Enabled'])
        # Data rows
        writer.writerows(csv_data)
    
    # Calculate total character count
    total_chars = sum(len(row[2]) for row in csv_data if row[1] == 'dialogue')
    
    print(f"✅ CSV file created: {output_file}")
    print(f"   Total rows: {len(csv_data)}")
    print(f"   Total dialogue characters: {total_chars}")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 convert_to_csv.py <input_script.md> <output_script.csv>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    convert_script_to_csv(input_file, output_file)
