import os
from itertools import islice
import numpy as np

from nextnanopy.utils.datasets import Variable, Coord
from nextnanopy.utils.mycollections import DictList


def load_message(method):
    def f(*args, **kwargs):
        # print('Loading...')
        result = method(*args, **kwargs)
        # print('Done!')

    return f


class Output(object):
    def __init__(self, fullpath):
        self.fullpath = fullpath
        self.metadata = {}
        self.coords = DictList()
        self.variables = DictList()

    @property
    def folder(self):
        return os.path.split(self.fullpath)[0]

    @property
    def filename(self):
        name = os.path.split(self.fullpath)[-1]
        return os.path.splitext(name)[0]

    @property
    def extension(self):
        return os.path.splitext(self.fullpath)[-1]

    @load_message
    def load(self):
        pass


class DataFileTemplate(Output):
    def __init__(self, fullpath, type=None):
        super().__init__(fullpath)
        self.type = type
        self.load()

    @load_message
    def load(self):
        loader = self.get_loader()
        df = loader(self.fullpath)
        self.update_with_datafile(df)
        del df

    def update_with_datafile(self, datafile):
        self.metadata.update(datafile.metadata)
        self.coords.update(datafile.coords)
        self.variables.update(datafile.variables)

    def get_loader(self):
        pass


class DataFile(DataFileTemplate):
    def __init__(self, fullpath, type=None):
        super().__init__(fullpath, type=type)

    def get_loader(self):
        if self.type == 'nextnano3':
            from nextnanopy.nn3.outputs import DataFile as loader
        elif self.type == 'nextnano++':
            from nextnanopy.nnp.outputs import DataFile as loader
        elif self.type == 'nextnano.NEGF':
            from nextnanopy.negf.outputs import DataFile as loader
        elif self.type == 'nextnano.MSB':
            raise NotImplementedError('Loading datafile from nextnano.MSB is not implemented yet')
        else:
            print('[Warning] nextnano type is not specified: nextnano++, nextnano3, nextnano.NEGF or nextnano.MSB')
            print('[Warning] Autosearching for the best loading method. Note: The result may not be correct')
            loader = self.find_loader()
        return loader

    def find_loader(self):
        from nextnanopy.nnp.outputs import DataFile as DataFile_nnp
        from nextnanopy.nn3.outputs import DataFile as DataFile_nn3
        from nextnanopy.negf.outputs import DataFile as DataFile_negf
        Dats = [DataFile_nn3, DataFile_nnp,DataFile_negf]
        for Dati in Dats:
            try:
                df = Dati(self.fullpath)
                if '' in df.variables.keys():
                    continue
                else:
                    break
            except:
                pass
        loader = Dati
        return loader


class AvsAscii(Output):
    def __init__(self, fullpath):
        super().__init__(fullpath)
        self.load()

    @property
    def fld(self):
        filename = self.filename + '.fld'
        return os.path.join(self.folder, filename)

    def load(self):
        self.load_raw_metadata()
        self.load_metadata()
        self.load_variables()
        self.load_coords()

    def load_raw_metadata(self):
        info = []
        with open(self.fld, 'r') as f:
            for line in f:
                line = line.replace('\n', '')
                line = line.strip()
                try:
                    float(line)
                    break
                except:
                    if line == '':
                        continue
                    if line[0] != '#':
                        info.append(line)
        return info

    def load_metadata(self):
        info = self.load_raw_metadata()
        key_int = ['ndim', 'dim1', 'dim2', 'dim3', 'nspace', 'veclen']
        key_str = ['data', 'field']
        metadata = {}
        metadata['labels'] = []
        metadata['units'] = []
        metadata['variables'] = []
        metadata['coords'] = []
        metadata['dims'] = []
        for line in info:
            key, value = line.split(maxsplit=1)
            if value[0] == '=':
                value = value.replace('=', '')
                value = value.strip()
                if key in key_int:
                    value = int(value)
                    metadata[key] = value
                elif key == 'label':
                    labels = value.split()
                    for label in labels:
                        if '[' in label:
                            label, unit = label.split('[')
                            unit = unit.split(']')[0]
                        else:
                            label = label
                            unit = ''
                        metadata['labels'].append(label)
                        metadata['units'].append(unit)
                else:
                    value = str(value)
                    metadata[key] = value

                if key[:3] == 'dim':
                    metadata['dims'].append(metadata[key])

            else:
                if key == 'variable':
                    vm = values_metadata(line)
                    vm['file'] = os.path.join(self.folder, vm['file'])
                    vm['size'] = np.prod(metadata['dims'])
                    metadata['variables'].append(vm)
                elif key == 'coord':
                    vm = values_metadata(line)
                    vm['file'] = os.path.join(self.folder, vm['file'])
                    num = vm['num']
                    vm['size'] = metadata[f'dim{num}']
                    metadata['coords'].append(vm)

        self.metadata = metadata
        return metadata

    def load_variables(self):
        meta = self.metadata
        variables = DictList()
        for vmeta, label, unit in zip(meta['variables'], meta['labels'], meta['units']):
            values = load_values(file=vmeta['file'],
                                 filetype=vmeta['filetype'],
                                 skip=vmeta['skip'],
                                 offset=vmeta['offset'],
                                 stride=vmeta['stride'],
                                 size=vmeta['size'])
            values = reshape_values(values, *meta['dims'])
            var = Variable(name=label, value=values, unit=unit, metadata=vmeta)
            variables[var.name] = var
        self.variables = variables
        return variables

    def load_coords(self):
        meta = self.metadata
        coords = DictList()
        for vmeta in meta['coords']:
            values = load_values(file=vmeta['file'],
                                 filetype=vmeta['filetype'],
                                 skip=vmeta['skip'],
                                 offset=vmeta['offset'],
                                 stride=vmeta['stride'],
                                 size=vmeta['size'])
            ax = coord_axis(vmeta['num'])
            unit = 'nm'
            var = Coord(name=ax, value=values, unit=unit, dim=vmeta['num'] - 1, metadata=vmeta)
            coords[var.name] = var
        self.coords = coords
        return coords


def coord_axis(dim):
    dim = str(dim)
    axes = {'1': 'x', '2': 'y', '3': 'z'}
    return axes[dim]


def values_metadata(line):
    """ Return a dict for: kind, num, file, filetype, skip, offset, stride"""
    metadata = {}
    kind, num, rest = line.split(maxsplit=2)
    metadata['kind'] = kind
    metadata['num'] = int(num)
    raw_rest = rest.split('=')
    raw_rest = [r.strip().split() for r in raw_rest]
    rest = []
    for ri in raw_rest:
        rest.extend(ri)
    keys = rest[0::2]
    values = rest[1::2]
    for key, value in zip(keys, values):
        key = key.strip()
        value = value.strip()
        if key in ['num', 'skip', 'offset', 'stride']:
            value = int(value)
        metadata[key] = value
    return metadata


def load_values(file, filetype='ascii', skip=0, offset=0, stride=1, size=None):
    """ Return flat array of floating values """
    stop = skip + size if size != None else None
    with open(file, 'r') as f:
        lines = islice(f, skip, stop, 1)
        values = [line.replace('\n', '').strip().split()[offset] for line in lines]
    return np.array(values, dtype=float)


def reshape_values(values, *dims):
    dims = np.flip(dims)
    shape = tuple([dim for dim in dims])
    values = np.reshape(values, shape)
    return np.transpose(values)


if __name__ == '__main__':
    import os

    folder_nnp = os.path.join('tests', 'datafiles', 'nextnano++')
    folder_nn3 = os.path.join('tests', 'datafiles', 'nextnano3')
    folder_negf = os.path.join('tests', 'datafiles', 'negf')
    file = 'bandedges_1d.dat'
    fp = os.path.join(folder_nnp, file)
    fp = os.path.join(folder_negf,'ReducedRealSpaceModes.dat')
    fp = os.path.join(folder_negf,'E_p (Kane energy).dat')
    fp = os.path.join(folder_nnp,'bandedges_2d.fld')

    # fp = os.path.join(folder_nn3,file)
    # from nextnanopy.negf.outputs import Dat
    fi = DataFile(fp,type='nextnano++')
