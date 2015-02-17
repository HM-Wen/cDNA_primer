##########################################################################
# Copyright (c) 2011-2014, Pacific Biosciences of California, Inc.
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted (subject to the limitations in the
# disclaimer below) provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright
#  notice, this list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above
#  copyright notice, this list of conditions and the following
#  disclaimer in the documentation and/or other materials provided
#  with the distribution.
#
#  * Neither the name of Pacific Biosciences nor the names of its
#  contributors may be used to endorse or promote products derived
#  from this software without specific prior written permission.
#
# NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE
# GRANTED BY THIS LICENSE. THIS SOFTWARE IS PROVIDED BY PACIFIC
# BIOSCIENCES AND ITS CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL PACIFIC BIOSCIENCES OR ITS
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#########################################################################

"""
Read and cache quality value from Base/CCS.H5 files.
"""

import os
import logging
from collections import defaultdict
import pbtools.pbtranscript.io.c_basQV as c_basQV
from pbcore.io.FastqIO import FastqReader

class h5_wrapper(object):

    """
    Wrap the .1.ccs.h5, .2.ccs.h5, .3.ccs.h5 to give the illusion of one
    (like what .bas.h5 does for .bax.h5)
    """

    def __init__(self, file_prefix, suffix='.ccs.h5'):
        """
        Expects <prefix>.1.ccs.h5, .2.ccs.h5, and .3.ccs.h5
        or .1.bax.h5, .2.bax.h5, .3.bax.h5
        """
        if suffix not in ('.ccs.h5', '.bax.h5'):
            errMsg = "bas.h5 is not supported, use ccs.h5 or bax.h5."
            raise ValueError(errMsg)
        self.files = [file_prefix + '.1' + suffix,
                      file_prefix + '.2' + suffix,
                      file_prefix + '.3' + suffix]
        # Sometimes may use only one bax.h5 file as input.
        # assert all(os.path.exists(f) for f in self.files)

        self.hn_range = [(0, 54493), (54494, 108987), (108988, 170000)]

    def __getitem__(self, seqid):
        if seqid.count('/') == 1 or seqid.count('/') == 2:
            hn = int(seqid.split('/')[1])
        else:
            errMsg = "Cannot recognize" + seqid
            logging.error(errMsg)
            raise ValueError(errMsg)

        for i in xrange(3):
            if self.hn_range[i][0] <= hn and \
               hn <= self.hn_range[i][1]:
                return self.files[i]

        errMsg = "Unlocated holeNumber" + hn
        raise ValueError(errMsg)

    def __delitem__(self, seqid):
        raise NotImplementedError("h5_wrapper.__delitem__ not implemented.")

    def __setitem__(self, seqid):
        raise NotImplementedError("h5_wrapper.__setitem__ not implemented.")

    def __len__(self, seqid):
        return len(self.files)


class basQVcacher:

    """Cache quality values from bas.h5 files."""
    qv_names = ['InsertionQV', 'SubstitutionQV', 'DeletionQV']

    def __init__(self):
        self.bas_dict = {}
        self.bas_files = {}

        # subread seqid --> qv_name --> list of qv (transformed to prob)
        self.qv = {}
        # smoothing window size, set when presmooth() is called
        self.window_size = None

    def get(self, seqid, qv_name, position=None):
        """Get quality value of type qv_name for a sequence seqid."""
        if position is None:
            return self.qv[seqid][qv_name]
        else:
            return self.qv[seqid][qv_name][position]

    def get_smoothed(self, seqid, qv_name, position=None):
        """Get smooth qv of type qv_name for seqid."""
        if position is None:
            return self.qv[seqid][qv_name + '_smoothed']
        else:
            return self.qv[seqid][qv_name + '_smoothed'][position]

    def add_bash5(self, bash5_filename):
        """Add a bas.h5/ccs.h5 to cacher."""
        basename = os.path.basename(bash5_filename)
        if bash5_filename.endswith('.bax.h5'):
            movie = basename[:-9]
            if movie not in self.bas_files:
                self.bas_files[movie] = h5_wrapper(bash5_filename[:-9],
                                                   suffix='.bax.h5')
        elif bash5_filename.endswith('.1.ccs.h5') or \
                bash5_filename.endswith('.2.ccs.h5') or \
                bash5_filename.endswith('.3.ccs.h5'):
            movie = basename[:-9]
            if movie not in self.bas_files:
                self.bas_files[movie] = h5_wrapper(bash5_filename[:-9])
        elif bash5_filename.endswith('.ccs.h5'):
            # a single .ccs.h5 (post 150k runs), treat the same as .bas.h5
            movie = basename[:-7]
            self.bas_files[movie] = defaultdict(lambda: bash5_filename)
        else:
            assert bash5_filename.endswith('.bas.h5')
            movie = basename[:-7]
            self.bas_files[movie] = defaultdict(lambda: bash5_filename)

    def precache(self, seqids):
        """
        Precache QV probabilities for seqids.
        """
        # for subread ex:
        # m120407_063017_4.../13/2571_3282
        # for CCS ex:
        # m120407_063017_4.../13/300_10_CCS

        # sort seqids by movie to save time
        seqids.sort(key=lambda x: (x.split('/')[0], int(x.split('/')[1])))

        # split seq IDs by bas filename
        # bas file --> list of seqids belonging to that bas file
        bas_job_dict = defaultdict(lambda: [])

        for seqid in seqids:
            # logging.debug("precaching " + seqid)
            movie, hn, _s_e = seqid.split('/')
            hn = int(hn)
            try:
                bas_file = self.bas_files[movie][seqid]
                bas_job_dict[bas_file].append(seqid)
            except KeyError:
                raise IOError("Could not read {s} from input bas/ccs fofn.".
                              format(s=seqid))

        for bas_file, seqids in bas_job_dict.iteritems():
            c_basQV.precache_helper(bas_file, seqids,
                                    basQVcacher.qv_names, self.qv)

    def presmooth(self, seqids, window_size):
        """
        precache MUST BE already called! Otherwise will have error!
        """
        self.window_size = window_size
        for seqid in seqids:
            # logging.debug("smoothing sequence " + seqid)
            # Replace .smooth_qv_regions by c_baseQV.maxval_per_window
            for qv_name in basQVcacher.qv_names:
                self.qv[seqid][qv_name + '_smoothed'] = \
                    c_basQV.maxval_per_window(self.qv[seqid][qv_name],
                                              window_size)

    def remove_unsmoothed(self):
        """Remove unsmoothed QVs."""
        for k, _v in self.qv.iteritems():
            for qv_name in basQVcacher.qv_names:
                try:
                    del self.qv[k][qv_name]
                except KeyError:
                    pass  # may have already been deleted. OK.

class fastqQVcacher:
    """
    Similar to basQVcacher except it reads from a FASTQ file
    So instead of having sub/ins/del QV, just one QV for all of them!

    Importantly it must have a get() and get_smoothed() function.
    It will simply ignore the <qv_type>.
    """
    def __init__(self):
        self.qv = {} # subread seqid --> None --> list of qv (transformed to prob)
        self.window_size = None # smoothing window size, set when presmooth() is called

    def get(self, seqid, qv_type, position=None):
        """
        <qv_type> is ignored
        """
        if position is None:
            return self.qv[seqid]['unsmoothed']
        else:
            return self.qv[seqid]['unsmoothed'][position]

    def get_smoothed(self, seqid, qv_type, position=None):
        """
        <qv_type> is ignored
        """
        if position is None:
            return self.qv[seqid]['smoothed']
        else:
            return self.qv[seqid]['smoothed'][position]

    def precache_fastq(self, fastq_filename):
        """
        Cache each sequence in the FASTQ file into self.qv
        """
        for r in FastqReader(fastq_filename):
            seqid = r.name.split()[0] 
            self.qv[seqid] = {}
            c_basQV.fastq_precache_helper(seqid, r.quality, self.qv)

    def presmooth(self, seqids, window_size):
        """
        precache MUST BE already called! Otherwise will have error!
        """
        self.window_size = window_size
        for seqid in seqids:
            self.qv[seqid]['smoothed'] = c_basQV.maxval_per_window(self.qv[seqid]['unsmoothed'], window_size)

    def remove_unsmoothed(self):
        for k,v in self.qv.iteritems():
            try:
                del self.qv[k]['unsmoothed']
            except KeyError:
                pass # may have already been deleted. OK.
                
                




