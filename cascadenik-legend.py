#!/usr/bin/env python

import os
import sys
import optparse
from math import pow
from os import mkdir, chmod
from os.path import isdir, realpath, expanduser, dirname, exists
from urlparse import urlparse

import cascadenik
import cascadenik.output as output
from cascadenik.compile import Directories

import tempfile
import mapnik2 as mapnik
import shapely.geometry
import posixpath

CACHE_DIR = '~/.cascadenik'

try:
    import xml.etree.ElementTree as ElementTree
    from xml.etree.ElementTree import Element
except ImportError:
    try:
        import lxml.etree as ElementTree
        from lxml.etree import Element
    except ImportError:
        import elementtree.ElementTree as ElementTree
        from elementtree.ElementTree import Element

class create_datasource:
    def __init__(self):
        self.datasource = mapnik.MemoryDatasource()
        self.ids = (i for i in xrange(1, 999999))
    def addFeatures(self, item, extent):
        for polygon_el in item.findall('polygon'):
            feature = mapnik.Feature(self.ids.next())
            for k in polygon_el.keys():
                feature[k] = polygon_el.get(k)
            feature.add_geometries_from_wkb(shapely.geometry.Polygon([(extent[0], extent[1]),(extent[2], extent[1]),(extent[2], extent[3]),(extent[0], extent[3]),(extent[0], extent[1])]).wkb)
            self.datasource.add_feature(feature)
        for line_el in item.findall('line'):
            feature = mapnik.Feature(self.ids.next())
            for k in line_el.keys():
                feature[k] = line_el.get(k)
            feature.add_geometries_from_wkb(shapely.geometry.LineString([(extent[0], 0),(0,0),(extent[2], 0)]).wkb)
            self.datasource.add_feature(feature)

        for point_el in item.findall('point'):
            feature = mapnik.Feature(self.ids.next())
            for k in point_el.keys():
                feature[k] = point_el.get(k)
            feature.add_geometries_from_wkb(shapely.geometry.Point(0,0).wkb)
            self.datasource.add_feature(feature)

    def to_mapnik(self):
        return self.datasource

def need_layer(element_classes, item, classes):
    if element_classes <= classes:
        return True
    for bgi in item.findall('background'):
        cls = set(bgi.get('class', '').split())
        if element_classes <= cls:
            return True
    return False

class legend_renderer:
    def __init__(self, src, dirs, verbose=False, srs=None, datasources_cfg=None):
        global VERBOSE

        if verbose:
            VERBOSE = True
            sys.stderr.write('\n')
    
        self.map_el = load_xml_file(src)
        self.dirs = dirs

        cascadenik._compile.expand_source_declarations(self.map_el, dirs, datasources_cfg)

        declarations = cascadenik._compile.extract_declarations(self.map_el, dirs)

        # a list of layers and a sequential ID generator
        self.layers, ids = [], (i for i in xrange(1, 999999))

        self.fontsets = []
        for fontset_el in self.map_el.findall('FontSet'):
            name = fontset_el.get('name', 'noName')
            face_names = [f.get('face_name') for f in fontset_el.findall('Font')]
            self.fontsets.append(output.Fontset(name,face_names))

        for layer_el in self.map_el.findall('Layer'):
    
            # nevermind with this one
            if layer_el.get('status', None) in ('off', '0', 0):
                continue

            layer_declarations = cascadenik._compile.get_applicable_declarations(layer_el, declarations)
        
            # a list of styles
            styles = []
        
            styles.append(output.Style('polygon style %d' % ids.next(),
                                       cascadenik._compile.get_polygon_rules(layer_declarations)))

            styles.append(output.Style('polygon pattern style %d' % ids.next(),
                                       cascadenik._compile.get_polygon_pattern_rules(layer_declarations, dirs)))

            styles.append(output.Style('raster style %d' % ids.next(),
                                       cascadenik._compile.get_raster_rules(layer_declarations)))

            styles.append(output.Style('line style %d' % ids.next(),
                                       cascadenik._compile.get_line_rules(layer_declarations)))

            styles.append(output.Style('line pattern style %d' % ids.next(),
                                       cascadenik._compile.get_line_pattern_rules(layer_declarations, dirs)))

            for (shield_name, shield_rules) in cascadenik._compile.get_shield_rule_groups(layer_declarations, dirs).items():
                styles.append(output.Style('shield style %d (%s)' % (ids.next(), shield_name), shield_rules))

            for (text_name, text_rules) in cascadenik._compile.get_text_rule_groups(layer_declarations).items():
                styles.append(output.Style('text style %d (%s)' % (ids.next(), text_name), text_rules))

            styles.append(output.Style('point style %d' % ids.next(),
                                       cascadenik._compile.get_point_rules(layer_declarations, dirs)))                                   
            styles = [s for s in styles if s.rules]
        
            if styles:
                minzoom = layer_el.get('min_zoom', None) and int(layer_el.get('min_zoom'))
                maxzoom = layer_el.get('max_zoom', None) and int(layer_el.get('max_zoom'))

                zooms = {
                     0: (500000000, 1000000000),
                     1: (200000000, 500000000),
                     2: (100000000, 200000000),
                     3: (50000000, 100000000),
                     4: (25000000, 50000000),
                     5: (12500000, 25000000),
                     6: (6500000, 12500000),
                     7: (3000000, 6500000),
                     8: (1500000, 3000000),
                     9: (750000, 1500000),
                    10: (400000, 750000),
                    11: (200000, 400000),
                    12: (100000, 200000),
                    13: (50000, 100000),
                    14: (25000, 50000),
                    15: (12500, 25000),
                    16: (5000, 12500),
                    17: (2500, 5000),
                    18: (1000, 2500),
                    19: (500, 1000),
                    20: (250, 500),
                    21: (100, 250),
                    22: (50, 100),
                   }

                if minzoom is not None and maxzoom is not None and minzoom < 23 and maxzoom < 23:
                    tminzoom = min(zooms[maxzoom])
                    maxzoom = max(zooms[minzoom])
                    minzoom = tminzoom

                layer = output.Layer('layer %d' % ids.next(),
                                     None, styles,
                                     layer_el.get('srs', None),
                                     minzoom,
                                     maxzoom)

                layer.classes = set(layer_el.get('class', '').split())
    
                self.layers.append(layer)
    
        self.map_attrs = cascadenik._compile.get_map_attributes(cascadenik._compile.get_applicable_declarations(self.map_el, declarations))
     
        # if a target srs is profiled, override whatever is in mml
        if srs is not None:
            self.map_el.set('srs', srs)
    


    def render(self, item, zoom, size, dest):
        """ Compile a Cascadenik MML file, returning a cascadenik.output.Map object.
    
        Parameters:
        
          src:
            Path to .mml file, or raw .mml file content.
          
          dirs:
            Object with directory names in 'cache', 'output', and 'source' attributes.
            dirs.source is expected to be fully-qualified, e.g. "http://example.com"
            or "file:///home/example".
        
        Keyword Parameters:
        
          verbose:
            If True, debugging information will be printed to stderr.
        
          srs:
            Target spatiral reference system for the compiled stylesheet.
            If provided, overrides default map srs in the .mml file.
        
          datasources_cfg:
            If a file or URL, uses the config to override datasources or parameters
            (i.e. postgis_dbname) defined in the map's canonical <DataSourcesConfig>
            entities.  This is most useful in development, whereby one redefines
            individual datasources, connection parameters, and/or local paths.
        """
        mmap = mapnik.Map(*size)
        mmap.srs = '+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null'

        resolution = 20037508.34/128/(pow(2,zoom))
        extent = [-resolution/2*size[0], -resolution/2*size[1], resolution/2*size[0], resolution/2*size[1]]

        classes = set(item.get('class', '').split())
    
        layers = []
    
        for layer in self.layers:
    
            # check if this layers classes are in class list
            if not need_layer(layer.classes, item, classes):
                continue

            datasource = create_datasource()
            
            if layer.classes <= classes:
                datasource.addFeatures(item,extent)

            for bg_el in item.findall('background'):
                bg_classes = set(bg_el.get('class', '').split())
                if layer.classes <= bg_classes:
                    datasource.addFeatures(bg_el,extent)

            layer.datasource = datasource
            layers.append(layer)
    
        output.Map(self.map_el.attrib.get('srs', None), layers, self.fontsets, **self.map_attrs).to_mapnik(mmap,self.dirs)
        bbox = mapnik.Envelope(*extent)
        mmap.zoom_to_box(bbox)
        mmap.background = mapnik.Color(0,0,0,0);
        im = mapnik.Image(*size)
        mapnik.render(mmap, im)
        im.save(dest,'png256')
        return im.tostring()

def load_xml_file(src):
    if posixpath.exists(src):
        doc = ElementTree.parse(src)
        return doc.getroot()
    else:
        try:
            # guessing src is a literal XML string?
            return ElementTree.fromstring(src)
        except:
            if not (src[:7] in ('http://', 'https:/', 'file://')):
                src = "file://" + src
            try:
                doc = ElementTree.parse(urllib.urlopen(src))
            except IOError, e:
                raise IOError('%s: %s' % (e,src))
            return doc.getroot()

def load_map_legend(src_file, legend_file, output_dir, cache_dir=None, datasources_cfg=None, verbose=False):
    scheme, n, path, p, q, f = urlparse(src_file)
    
    if scheme in ('file', ''):
        assert exists(src_file), "We'd prefer an input file that exists to one that doesn't"
    
    if cache_dir is None:
        cache_dir = expanduser(CACHE_DIR)
        
        # only make the cache dir if it wasn't user-provided
        if not isdir(cache_dir):
            mkdir(cache_dir)
            chmod(cache_dir, 0755)

    dirs = Directories(output_dir, realpath(cache_dir), dirname(src_file))

    renderer = legend_renderer(src_file,dirs)

    legend_el = load_xml_file(legend_file)

    size = [int(legend_el.get('width', '30')), int(legend_el.get('height', '20'))]

    empty_text=legend_el.get('emptyText', '');

    ids = (i for i in xrange(1, 999999))

    dest = output_dir + "/empty.png"
    empty = renderer.render(ElementTree.fromstring("<item />"),0,size,dest)
    for zoom in range(0,19):
        output = "<table class=\"legend_table\">"
        elems_in_cat = -99999
        for item_el in legend_el:
            if item_el.tag == 'item':
                # nevermind with this one
                if item_el.get('status', None) in ('off', '0', 0):
                    continue
                destf = "z" + str(zoom) +"_" +str(ids.next()) + ".png"
                dest = output_dir + "/" + destf
                img = renderer.render(item_el,zoom,size,dest)
                if img == empty:
                    os.unlink(dest)
                else:
                    output+="<tr><td class=\"legend_image\"><img src=\""+output_dir+"/"+destf+"\" width=\""+str(size[0])+"\" height=\""+str(size[1])+"\" alt=\""+item_el.get('label', '')+"\"/></td><td class=\"legend_label\">"+item_el.get('label', '')+"</td></tr>"
                    elems_in_cat+=1
            elif item_el.tag == 'title':
                if elems_in_cat == 0:
                    output+="<tr><td /><td>"+empty_text+"</td></tr>"
                output+="<tr><td class=\"legend_headline\" colspan=\"2\">"+item_el.text+"</td></tr>"
                elems_in_cat = 0
        if elems_in_cat == 0:
            output+="<tr><td /><td>"+empty_text+"</td></tr>"
        output += "</table>"
        f=open(output_dir + "/_z" + str(zoom) + ".html", 'w')
        f.write(output)


def main(src_file, legend_file, dest_dir, **kwargs):
    """ Given an input layers file and a directory, print the compiled
        XML file to stdout and save any encountered external image files
        to the named directory.
    """
    if not isdir(dest_dir):
        mkdir(dest_dir)
        chmod(dest_dir, 0755)

    load_kwargs = dict([(k, v) for (k, v) in kwargs.items() if k in ('cache_dir', 'verbose', 'datasources_cfg')])
    load_map_legend(src_file, legend_file, dest_dir, **load_kwargs)
    
    return 0

parser = optparse.OptionParser(usage="""%prog [options] <mml> <xml>""", version='%prog ' + cascadenik.__version__)

parser.set_defaults(cache_dir=None, pretty=True, verbose=False, datasources_cfg=None)

# the actual default for cache_dir is handled in load_map(),
# to ensure that the mkdir behavior is correct.
parser.add_option('-c', '--cache-dir', dest='cache_dir',
                  help='Cache file-based resources (symbols, shapefiles, etc) to this directory. (default: %s)' % cascadenik.CACHE_DIR)

parser.add_option('-d' , '--datasources-config', dest='datasources_cfg',
                  help='Use the specified .cfg file to provide local overrides to datasources and variables.',
                  type="string")

parser.add_option('--srs', dest='srs',
                  help='Target srs for the compiled stylesheet. If provided, overrides default map srs in the mml. (default: None)')

parser.add_option('-p', '--pretty', dest='pretty',
                  help='Pretty print the xml output. (default: True)',
                  action='store_true')

parser.add_option('-v' , '--verbose', dest='verbose',
                  help='Make a bunch of noise. (default: False)',
                  action='store_true')

if __name__ == '__main__':
    (options, args) = parser.parse_args()
    
    if not len(args) == 3:
        parser.error('Please specify .mml, .xml files and output directory')

    layersfile, legendfile, outputdir = args[0:3]
    
    print >> sys.stderr, 'output file:', outputdir, dirname(realpath(legendfile))

    if not layersfile.endswith('.mml'):
        parser.error('Input style must be an .mml file')

    if not legendfile.endswith('.xml'):
        parser.error('Input legend must be an .xml file')

    sys.exit(main(layersfile, legendfile, outputdir, **options.__dict__))
