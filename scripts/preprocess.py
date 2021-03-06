# -*- coding: utf-8 -*-

import argparse, json, os
import numpy as np
import h5py
import codecs
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--input_txt', default='data/tiny-shakespeare.txt')
parser.add_argument('--output_h5', default='data/tiny-shakespeare.h5')
parser.add_argument('--output_json', default='data/tiny-shakespeare.json')
parser.add_argument('--val_frac', type=float, default=0.1)
parser.add_argument('--test_frac', type=float, default=0.1)
parser.add_argument('--quiet', action='store_true')
parser.add_argument('--syllabic', default='none')
parser.add_argument('--syllsec', default='none')
parser.add_argument('--encoding', default='utf-8')
args = parser.parse_args()


if __name__ == '__main__':
  if args.encoding == 'bytes': args.encoding = None

  # First go the file once to see how big it is and to build the vocab
  if args.syllabic == 'none' :
    if args.syllsec != 'none':
      print 'Error: Secondary hyphenator specified with syllabic prediction disabled'
      sys.exit(0)
    syllabic = False
    token_to_idx = {}
    total_size = 0
    with codecs.open(args.input_txt, 'r', args.encoding) as f:
      for line in f:
        total_size += len(line)
        for char in line:
          if char not in token_to_idx:
            token_to_idx[char] = len(token_to_idx) + 1
  else : 
      syllabic = True

      def detectDictionaryFallback(language):
        if not (language in pyphen.LANGUAGES) :
          fallback = pyphen.language_fallback(language)
          if fallback is None:
            print 'Syllabic dictionary', language, 'is unavailable'
            sys.exit(0)
          else:
            print 'Warning: dictionary', language, 'is unavailable, using', fallback, 'as fallback'
            language = fallback
          return language
	return language

      import unicodedata
      import pyphen
      primary = pyphen.Pyphen(lang=detectDictionaryFallback(args.syllabic))
      if args.syllabic == args.syllsec or args.syllsec == 'none':
        secondary = None
      else:
        secondary = pyphen.Pyphen(lang=detectDictionaryFallback(args.syllsec))

      def scanSyllables(stream, encoding, processing) : 
        word = ''
        space = False
        with codecs.open(stream, 'r', encoding) as f:
          for line in f:
            for char in line:
              cat = unicodedata.category(char)
              if cat[0]=='L' :
                  word = word + char
                  space = False
                  continue
              if len(word)>0 :
                  splits = primary.positions(word.lower())
                  if secondary:
                    secsplits = secondary.positions(word.lower())
                  else:
                    secsplits = []
                  if len(secsplits) > len(splits):
                    splits = secsplits
                  syls = splitWord(word.lower(), splits)
                  word = ''
              else :
                  syls = [ ]
              if cat[0]=='Z' :
                if not space : syls.append( u' ' )
                space = True              
              elif cat[0]=='N' or cat[0]=='P' :
                syls.append( char )
                space = False
              elif char == u'\n' :
                syls.append( char )
                space = False
              for syl in syls :
                  processing(syl)

      def createVocab(syl) : 
        global token_to_idx
        global total_size
        total_size += 1
        if syl not in token_to_idx:
          token_to_idx[syl] = len(token_to_idx) + 1
      
      def splitWord(word, splits) :
        if len(splits) == 0:
          return [word]
        else:
          firstidx = 0
          lastidx = 0
          syls = []
          while splits:
            firstidx = lastidx
            lastidx = splits.pop(0)
            syls.append(word[firstidx:lastidx])
          syls.append(word[lastidx:])
          return syls
          
      token_to_idx = { u'\n' : 1 }
      total_size = 0
      scanSyllables(args.input_txt, args.encoding, createVocab)

  # Now we can figure out the split sizes
  val_size = int(args.val_frac * total_size)
  test_size = int(args.test_frac * total_size)
  train_size = total_size - val_size - test_size
 
  if not args.quiet:
    print 'Total vocabulary size: %d' % len(token_to_idx)
    print 'Total tokens in file: %d' % total_size
    print '  Training size: %d' % train_size
    print '  Val size: %d' % val_size
    print '  Test size: %d' % test_size

  # Choose the datatype based on the vocabulary size
  dtype = np.uint8
  if len(token_to_idx) > 255:
    dtype = np.uint32
  if not args.quiet:
    print 'Using dtype ', dtype

  # Just load data into memory ... we'll have to do something more clever
  # for huge datasets but this should be fine for now
  train = np.zeros(train_size, dtype=dtype)
  val = np.zeros(val_size, dtype=dtype)
  test = np.zeros(test_size, dtype=dtype)
  splits = [train, val, test]

  # Go through the file again and write data to numpy arrays
  split_idx, cur_idx = 0, 0
  if not syllabic : 
    with codecs.open(args.input_txt, 'r', args.encoding) as f:
      for line in f:
        for char in line:
          splits[split_idx][cur_idx] = token_to_idx[char]
          cur_idx += 1
          if cur_idx == splits[split_idx].size:
            split_idx += 1
            cur_idx = 0
  else :

    def convertInput(syl) : 
      global check_size
      global splits
      global split_idx
      global cur_idx
      global token_to_idx
      check_size += 1
      # print check_size, syl
      splits[split_idx][cur_idx] = token_to_idx[syl]
      cur_idx += 1
      if cur_idx == splits[split_idx].size:
        split_idx += 1
        cur_idx = 0

    check_size = 0
    scanSyllables(args.input_txt, args.encoding, convertInput)

    if total_size != check_size :
      print 'WARNING : File sizes mismatched between vocabulary building (', total_size, ') and token conversion (', check_size, ')'
    if cur_idx!=0  :
      print 'ERROR : File size mismatched between splits. cur_idx =', cur_idx
      sys.exit(1)

  # Write data to HDF5 file
  with h5py.File(args.output_h5, 'w') as f:
    f.create_dataset('train', data=train)
    f.create_dataset('val', data=val)
    f.create_dataset('test', data=test)

  # For 'bytes' encoding, replace non-ascii characters so the json dump
  # doesn't crash
  if args.encoding is None:
    new_token_to_idx = {}
    for token, idx in token_to_idx.iteritems():
      if ord(token) > 127:
        new_token_to_idx['[%d]' % ord(token)] = idx
      else:
        new_token_to_idx[token] = idx
    token_to_idx = new_token_to_idx

  # Dump a JSON file for the vocab
  json_data = {
    'token_to_idx': token_to_idx,
    'idx_to_token': {v: k for k, v in token_to_idx.iteritems()},
  }
  with open(args.output_json, 'w') as f:
    json.dump(json_data, f)
